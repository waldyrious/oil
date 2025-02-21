"""
expr_parse.py
"""
from __future__ import print_function

import sys

from _devbuild.gen.syntax_asdl import (
    token, word__Token, word__Compound, word_part
)
from _devbuild.gen.id_kind_asdl import Id, Kind
from _devbuild.gen.types_asdl import lex_mode_e

from core import meta
from core import util
#from core.util import log
from core.util import p_die
from frontend import reader
from osh import braces
from osh import word_
from pgen2 import parse

from typing import TYPE_CHECKING, IO, Dict, Tuple, cast
if TYPE_CHECKING:
  from frontend.lexer import Lexer
  from frontend.parse_lib import ParseContext
  from pgen2.grammar import Grammar
  from pgen2.parse import PNode


class ParseTreePrinter(object):
  """Prints a tree of PNode instances."""
  def __init__(self, names):
    # type: (Dict[int, str]) -> None
    self.names = names

  def Print(self, pnode, f=sys.stdout, indent=0, i=0):
    # type: (PNode, IO[str], int, int) -> None

    ind = '  ' * indent
    # NOTE:
    # - value is filled in for TOKENS, but it's always None for PRODUCTIONS.
    # - context is (prefix, (lineno, column)), where lineno is 1-based, and
    #   'prefix' is a string of whitespace.
    #   e.g. for 'f(1, 3)', the "3" token has a prefix of ' '.
    if isinstance(pnode.tok, tuple):
      v = pnode.tok[0]
    elif isinstance(pnode.tok, token):
      v = pnode.tok.val
    else:
      v = '-'
    f.write('%s%d %s %s\n' % (ind, i, self.names[pnode.typ], v))
    if pnode.children:  # could be None
      for i, child in enumerate(pnode.children):
        self.Print(child, indent=indent+1, i=i)


def _Classify(gr, tok):
  # type: (Grammar, token) -> int

  # We have to match up what ParserGenerator.make_grammar() did when
  # calling make_label() and make_first().  See classify() in
  # opy/pgen2/driver.py.

  # 'x' and 'for' are both tokenized as Expr_Name.  This handles the 'for'
  # case.
  if tok.id == Id.Expr_Name:
    ilabel = gr.keywords.get(tok.val)
    if ilabel is not None:
      return ilabel

  # This handles 'x'.
  typ = tok.id.enum_id
  ilabel = gr.tokens.get(typ)
  if ilabel is not None:
    return ilabel

  #log('NAME = %s', tok.id.name)
  # 'Op_RBracket' ->
  # Never needed this?
  #id_ = TERMINALS.get(tok.id.name)
  #if id_ is not None:
  #  return id_.enum_id

  raise AssertionError('%d not a keyword and not in gr.tokens: %s' % (typ, tok))


# NOTE: this model is not NOT expressive enough for:
#
# x = func(x, y='default', z={}) {
#   echo hi
# }

# That can probably be handled with some state machine.  Or maybe:
# https://en.wikipedia.org/wiki/Dyck_language
# When you see "func", start matching () and {}, until you hit a new {.
# It's not a regular expression.
#
# Or even more simply:
#   var x = 1 + 2 
# vs.
#   echo hi = 1

# Other issues:
# - Command and Array could be combined?  The parsing of { is different, not
# the lexing.
# - What about SingleLine mode?  With a % prefix?
#   - Assumes {} means brace sub, and also makes trailing \ unnecessary?
#   - Allows you to align pipes on the left
#   - does it mean that only \n\n is a newline?

POP = lex_mode_e.Undefined

_MODE_TRANSITIONS = {
    # DQ_Oil -> ...
    (lex_mode_e.DQ_Oil, Id.Left_DollarSlash): lex_mode_e.Regex,  # "$/ any + /"
    # TODO: Add a token for $/ 'foo' /i .
    # Long version is RegExp($/ 'foo' /, ICASE|DOTALL) ?  Or maybe Regular()
    (lex_mode_e.Regex, Id.Arith_Slash): POP,

    (lex_mode_e.DQ_Oil, Id.Left_DollarBrace): lex_mode_e.VSub_Oil,  # "${x|html}"
    (lex_mode_e.VSub_Oil, Id.Op_RBrace): POP,
    (lex_mode_e.DQ_Oil, Id.Left_DollarBracket): lex_mode_e.Command,  # "$[echo hi]"
    (lex_mode_e.Command, Id.Op_RBracket): POP,
    (lex_mode_e.DQ_Oil, Id.Left_DollarParen): lex_mode_e.Expr,  # "$(1 + 2)"
    (lex_mode_e.Expr, Id.Op_RParen): POP,

    # Expr -> ...
    (lex_mode_e.Expr, Id.Left_AtBracket): lex_mode_e.Array,  # x + @[1 2]
    (lex_mode_e.Array, Id.Op_RBracket): POP,

    (lex_mode_e.Expr, Id.Left_DollarSlash): lex_mode_e.Regex,  # $/ any + /
    (lex_mode_e.Expr, Id.Left_DollarBrace): lex_mode_e.VSub_Oil,  # ${x|html}
    (lex_mode_e.Expr, Id.Left_DollarBracket): lex_mode_e.Command,  # $[echo hi]
    (lex_mode_e.Expr, Id.Op_LParen): lex_mode_e.Expr,  # $( f(x) )

    (lex_mode_e.Expr, Id.Left_DoubleQuote): lex_mode_e.DQ_Oil,  # x + "foo"
    (lex_mode_e.DQ_Oil, Id.Right_DoubleQuote): POP,

    # Regex
    (lex_mode_e.Regex, Id.Op_LBracket): lex_mode_e.CharClass,  # $/ 'foo.' [c h] /
    (lex_mode_e.CharClass, Id.Op_RBracket): POP,

    (lex_mode_e.Regex, Id.Left_DoubleQuote): lex_mode_e.DQ_Oil,  # $/ "foo" /
    # POP is done above

    (lex_mode_e.Array, Id.Op_LBracket): lex_mode_e.CharClass,  # @[ a *.[c h] ]
    # POP is done above
}

# For ignoring newlines.
_OTHER_BALANCE = {
    Id.Op_LParen:  1,
    Id.Op_RParen: -1,

    Id.Op_LBracket:  1,
    Id.Op_RBracket: -1,

    Id.Op_LBrace:  1,
    Id.Op_RBrace: -1
}


def _PushOilTokens(parse_ctx, gr, p, lex):
  # type: (ParseContext, Grammar, parse.Parser, Lexer) -> token
  """Push tokens onto pgen2's parser.

  Returns the last token so it can be reused/seen by the CommandParser.
  """
  #log('keywords = %s', gr.keywords)
  #log('tokens = %s', gr.tokens)

  mode = lex_mode_e.Expr
  mode_stack = [mode]

  balance = 0

  from core.util import log
  while True:
    tok = lex.Read(mode)
    #log('tok = %s', tok)

    # Comments and whitespace.  Newlines aren't ignored.
    if meta.LookupKind(tok.id) == Kind.Ignored:
      continue

    # For var x = {
    #   a: 1, b: 2
    # }
    if balance > 0 and tok.id == Id.Op_Newline:
      #log('*** SKIPPING NEWLINE')
      continue

    action = _MODE_TRANSITIONS.get((mode, tok.id))
    if action == POP:
      mode_stack.pop()
      mode = mode_stack[-1]
      balance -= 1
      #log('POPPED to %s', mode)
    elif action:  # it's an Id
      new_mode = action
      mode_stack.append(new_mode)
      mode = new_mode
      balance += 1  # e.g. var x = $/ NEWLINE /
      #log('PUSHED to %s', mode)
    else:
      # If we didn't already so something with the balance, look at another table.
      balance += _OTHER_BALANCE.get(tok.id, 0)
      #log('BALANCE after seeing %s = %d', tok.id, balance)

    #if tok.id == Id.Expr_Name and tok.val in KEYWORDS:
    #  tok.id = KEYWORDS[tok.val]
    #  log('Replaced with %s', tok.id)

    if tok.id.enum_id >= 256:
      raise AssertionError(str(tok))

    ilabel = _Classify(gr, tok)
    #log('tok = %s, ilabel = %d', tok, ilabel)

    if p.addtoken(tok.id.enum_id, tok, ilabel):
      return tok

    #
    # Extra handling of the body of @() and $().  Lex in the ShCommand mode.
    #

    if tok.id == Id.Left_AtParen:
      # NOTE: Not using Right_ArrayLiteral like command mode one.  That is only
      # for command sub I believe.
      lex.PushHint(Id.Op_RParen, Id.Right_ArrayLiteral)

      # Blame the opening token
      line_reader = reader.DisallowedLineReader(parse_ctx.arena, tok)
      w_parser = parse_ctx.MakeWordParser(lex, line_reader)
      words = []
      while True:
        w = w_parser.ReadWord(lex_mode_e.ShCommand)
        if 0:
          log('w = %s', w)

        if isinstance(w, word__Token):
          word_id = word_.CommandId(w)
          if word_id == Id.Right_ArrayLiteral:
            break
          elif word_id == Id.Op_Newline:  # internal newlines allowed
            continue
          else:
            # Token
            p_die('Unexpected token in array literal: %r', w.token.val, word=w)

        assert isinstance(w, word__Compound)  # for MyPy
        words.append(w)

      words2 = braces.BraceDetectAll(words)
      words3 = word_.TildeDetectAll(words2)

      #log('pushing Expr_WordsDummy')
      typ = Id.Expr_WordsDummy.enum_id
      opaque = cast(token, words3)  # HACK for expr_to_ast
      ilabel = gr.tokens[typ]
      done = p.addtoken(typ, opaque, ilabel)
      assert not done  # can't end the expression

      # Now push the closing )
      tok = w.token
      ilabel = _Classify(gr, tok)
      done = p.addtoken(tok.id.enum_id, tok, ilabel)
      assert not done  # can't end the expression

      continue

    if tok.id == Id.Left_DollarParen:
      left_token = tok

      lex.PushHint(Id.Op_RParen, Id.Eof_RParen)
      line_reader = reader.DisallowedLineReader(parse_ctx.arena, tok)
      c_parser = parse_ctx.MakeParserForCommandSub(line_reader, lex,
                                                   Id.Eof_RParen)
      node = c_parser.ParseCommandSub()
      # A little gross: Copied from osh/word_parse.py
      right_token = c_parser.w_parser.cur_token

      cs_part = word_part.CommandSub(left_token, node)
      cs_part.spids.append(left_token.span_id)
      cs_part.spids.append(right_token.span_id)

      typ = Id.Expr_CommandDummy.enum_id
      opaque = cast(token, cs_part)  # HACK for expr_to_ast
      ilabel = gr.tokens[typ]
      done = p.addtoken(typ, opaque, ilabel)
      assert not done  # can't end the expression

      # Now push the closing )
      ilabel = _Classify(gr, right_token)
      done = p.addtoken(right_token.id.enum_id, right_token, ilabel)
      assert not done  # can't end the expression

      continue

  else:
    # We never broke out -- EOF is too soon (how can this happen???)
    raise parse.ParseError("incomplete input", tok.id.enum_id, tok)


def NoSingletonAction(gr, pnode):
  # type: (Grammar, PNode) -> PNode
  """Collapse parse tree."""
  # hm this was so easy!  Why do CPython and pgen2 materialize so much then?
  children = pnode.children
  if children is not None and len(children) == 1:
    return children[0]

  return pnode


class ExprParser(object):
  """A wrapper around a pgen2 parser."""

  def __init__(self, parse_ctx, gr):
    # type: (ParseContext, Grammar) -> None
    self.parse_ctx = parse_ctx
    self.gr = gr
    # Reused multiple times.
    self.push_parser = parse.Parser(gr, convert=NoSingletonAction)

  def Parse(self, lexer, start_symbol):
    # type: (Lexer, int) -> Tuple[PNode, token]

    # Reuse the parser
    self.push_parser.setup(start_symbol)
    try:
      last_token = _PushOilTokens(self.parse_ctx, self.gr, self.push_parser,
                                  lexer)
    except parse.ParseError as e:
      #log('ERROR %s', e)
      # TODO:
      # - Describe what lexer mode we're in (Invalid syntax in regex)
      #   - Maybe say where the mode started
      # - Id.Unknown_Tok could say "This character is invalid"
      raise util.ParseError('Invalid syntax', token=e.opaque)

    return self.push_parser.rootnode, last_token
