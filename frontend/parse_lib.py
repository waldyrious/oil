"""
parse_lib.py - Consolidate various parser instantiations here.
"""

from _devbuild.gen.id_kind_asdl import Id_t
from _devbuild.gen.syntax_asdl import (
    token, command_t, expr_t, word_t, redir_t, word__Compound,
    param, type_expr_t
)
from _devbuild.gen.types_asdl import lex_mode_e
from _devbuild.gen import grammar_nt

from core import meta
from core.util import p_die
from frontend import lexer
from frontend import reader
from frontend import tdop
from frontend import match

from oil_lang import expr_parse
from oil_lang import expr_to_ast
from osh import arith_parse
from osh import cmd_parse
from osh import word_parse

#from oil_lang import cmd_parse as oil_cmd_parse

from typing import Any, List, Tuple, Dict, Optional, IO, TYPE_CHECKING
if TYPE_CHECKING:
  from core.alloc import Arena
  from core.util import DebugFile
  from frontend.lexer import Lexer
  from frontend.reader import _Reader
  from frontend.tdop import TdopParser
  from osh.word_parse import WordParser
  from osh.cmd_parse import CommandParser
  from pgen2.grammar import Grammar
  from pgen2.parse import PNode

class _BaseTrail(object):

  def __init__(self):
    # type: () -> None
    # word from a partially completed command.
    # Filled in by _ScanSimpleCommand in osh/cmd_parse.py.
    self.words = []  # type: List[word__Compound]
    self.redirects = []  # type: List[redir_t]
    # TODO: We should maintain the LST invariant and have a single list, but
    # that I ran into the "cases classes are better than variants" problem.

    # Non-ignored tokens, after PushHint translation.  Used for variable name
    # completion.  Filled in by _Peek() in osh/word_parse.py.
    #
    # Example:
    # $ echo $\
    # f<TAB>   
    # This could complete $foo.
    # Problem: readline doesn't even allow that, because it spans more than one
    # line!
    self.tokens = []  # type: List[token]

    self.alias_words = []  # type: List[word__Compound]  # words INSIDE an alias expansion
    self.expanding_alias = False

  def Clear(self):
    # type: () -> None
    pass

  def SetLatestWords(self, words, redirects):
    # type: (List[word__Compound], List[redir_t]) -> None
    pass

  def AppendToken(self, token):
    # type: (token) -> None
    pass

  def BeginAliasExpansion(self):
    # type: () -> None
    pass

  def EndAliasExpansion(self):
    # type: () -> None
    pass

  def PrintDebugString(self, debug_f):
    # type: (DebugFile) -> None

    # note: could cast DebugFile to IO[str] instead of ignoring?
    debug_f.log('  words:')
    for w in self.words:
      w.PrettyPrint(f=debug_f)  # type: ignore
    debug_f.log('')

    debug_f.log('  redirects:')
    for r in self.redirects:
      r.PrettyPrint(f=debug_f)  # type: ignore
    debug_f.log('')

    debug_f.log('  tokens:')
    for p in self.tokens:
      p.PrettyPrint(f=debug_f)  # type: ignore
    debug_f.log('')

    debug_f.log('  alias_words:')
    for w in self.alias_words:
      w.PrettyPrint(f=debug_f)  # type: ignore
    debug_f.log('')

  def __repr__(self):
    # type: () -> str
    return '<Trail %s %s %s %s>' % (
        self.words, self.redirects, self.tokens, self.alias_words)


class _NullTrail(_BaseTrail):
  """Used when we're not completing."""
  pass


class Trail(_BaseTrail):
  """Info left by the parser to help us complete shell syntax and commands.

  It's also used for history expansion.
  """
  def Clear(self):
    # type: () -> None
    del self.words[:]
    del self.redirects[:]
    # The other ones don't need to be reset?
    del self.tokens[:]
    del self.alias_words[:]

  def SetLatestWords(self, words, redirects):
    # type: (List[word__Compound], List[redir_t]) -> None
    if self.expanding_alias:
      self.alias_words = words  # Save these separately
      return
    self.words = words
    self.redirects = redirects

  def AppendToken(self, token):
    # type: (token) -> None
    if self.expanding_alias:  # We don't want tokens inside aliases
      return
    self.tokens.append(token)

  def BeginAliasExpansion(self):
    # type: () -> None
    """Called by CommandParser so we know to be ready for FIRST alias word.

    For example, for

    alias ll='ls -l'

    Then we want to capture 'ls' as the first word.

    We do NOT want SetLatestWords or AppendToken to be active, because we don't
    need other tokens from 'ls -l'.
    
    It would also probably cause bugs in history expansion, e.g. echo !1 should
    be the first word the user typed, not the first word after alias expansion.
    """
    self.expanding_alias = True

  def EndAliasExpansion(self):
    # type: () -> None
    """Go back to the normal trail collection mode."""
    self.expanding_alias = False


if TYPE_CHECKING:
  AliasesInFlight = List[Tuple[str, int]]


def MakeGrammarNames(oil_grammar):
  # type: (Grammar) -> Dict[int, str]

  names = {}

  for id_name, k in meta.ID_SPEC.id_str2int.items():
    # Hm some are out of range
    #assert k < 256, (k, id_name)

    # HACK: Cut it off at 256 now!  Expr/Arith/Op doesn't go higher than
    # that.  TODO: Change NT_OFFSET?  That might affect C code though.
    # Best to keep everything fed to pgen under 256.  This only affects
    # pretty printing.
    if k < 256:
      names[k] = id_name

  for k, v in oil_grammar.number2symbol.items():
    # eval_input == 256.  Remove?
    assert k >= 256, (k, v)
    names[k] = v

  return names


class OilParseOptions(object):

  def __init__(self):
    # type: () -> None
    self.at = False  # @foo, @array(a, b)
    self.brace = False  # cd /bin { ... }
    self.paren = False  # if (x > 0) ...

    # all:nice
    self.equals = False  # x = 'var'
    self.set = False  # set x = 'var'

  #def __str__(self):
  #  return str(self.__dict__)


class ParseContext(object):
  """Context shared between the mutually recursive Command and Word parsers.

  In constrast, STATE is stored in the CommandParser and WordParser instances.
  """

  def __init__(self, arena, parse_opts, aliases, oil_grammar, trail=None,
               one_pass_parse=False):
    # type: (Arena, OilParseOptions, Dict[str, Any], Grammar, Optional[_BaseTrail], bool) -> None
    self.arena = arena
    self.parse_opts = parse_opts
    self.aliases = aliases

    self.e_parser = expr_parse.ExprParser(self, oil_grammar)
    # NOTE: The transformer is really a pure function.
    if oil_grammar:
      self.tr = expr_to_ast.Transformer(oil_grammar)
      names = MakeGrammarNames(oil_grammar)
    else:  # hack for unit tests, which pass None
      self.tr = None
      names = {}

    self.parsing_expr = False  # "single-threaded" state

    # Completion state lives here since it may span multiple parsers.
    self.trail = trail or _NullTrail()
    self.one_pass_parse = one_pass_parse

    self.p_printer = expr_parse.ParseTreePrinter(names)  # print raw nodes

  def _MakeLexer(self, line_reader):
    # type: (_Reader) -> Lexer
    """Helper function.

    NOTE: I tried to combine the LineLexer and Lexer, and it didn't perform
    better.
    """
    line_lexer = lexer.LineLexer(match.MATCHER, '', self.arena)
    return lexer.Lexer(line_lexer, line_reader)

  def MakeOshParser(self, line_reader, emit_comp_dummy=False,
                    aliases_in_flight=None):
    # type: (_Reader, bool, Optional[AliasesInFlight]) -> CommandParser
    lx = self._MakeLexer(line_reader)
    if emit_comp_dummy:
      lx.EmitCompDummy()  # A special token before EOF!

    w_parser = word_parse.WordParser(self, lx, line_reader)
    c_parser = cmd_parse.CommandParser(self, w_parser, lx, line_reader,
                                       aliases_in_flight=aliases_in_flight)
    return c_parser

  def MakeOilCommandParser(self, line_reader):
    # type: (_Reader) -> None
    # Same lexer as Oil?  It just doesn't start in the OUTER state?
    lx = self._MakeLexer(line_reader)
    #c_parser = oil_cmd_parse.OilParser(self, lx, line_reader)
    #return c_parser
    return None

  def MakeWordParserForHereDoc(self, line_reader):
    # type: (_Reader) -> WordParser
    lx = self._MakeLexer(line_reader)
    return word_parse.WordParser(self, lx, line_reader)

  def MakeWordParser(self, lx, line_reader):
    # type: (Lexer, _Reader) -> WordParser
    return word_parse.WordParser(self, lx, line_reader)

  def MakeArithParser(self, code_str):
    # type: (str) -> TdopParser
    """Used for a[x+1]=foo in the CommandParser."""
    line_reader = reader.StringLineReader(code_str, self.arena)
    lx = self._MakeLexer(line_reader)
    w_parser = word_parse.WordParser(self, lx, line_reader,
                                     lex_mode=lex_mode_e.Arith)
    a_parser = tdop.TdopParser(arith_parse.SPEC, w_parser)
    return a_parser

  def MakeParserForCommandSub(self, line_reader, lexer, eof_id):
    # type: (_Reader, Lexer, Id_t) -> CommandParser
    """To parse command sub, we want a fresh word parser state."""
    w_parser = word_parse.WordParser(self, lexer, line_reader)
    c_parser = cmd_parse.CommandParser(self, w_parser, lexer, line_reader,
                                       eof_id=eof_id)
    return c_parser

  def MakeWordParserForPlugin(self, code_str):
    # type: (str) -> WordParser
    """For $PS1, $PS4, etc."""
    line_reader = reader.StringLineReader(code_str, self.arena)
    lx = self._MakeLexer(line_reader)
    return word_parse.WordParser(self, lx, line_reader)

  def _ParseOil(self, lexer, start_symbol):
    # type: (Lexer, int) -> Tuple[PNode, token]
    """Helper Oil expression parsing."""
    self.parsing_expr = True
    try:
      return self.e_parser.Parse(lexer, grammar_nt.oil_arglist)
    finally:
      self.parsing_expr = False

  def ParseOilAssign(self, kw_token, lexer, start_symbol,
                     print_parse_tree=False):
    # type: (token, Lexer, int, bool) -> Tuple[command_t, token]
    """e.g. var mylist = [1, 2, 3]"""

    # TODO: We do need re-entracy for var x = @[ (1+2) ] and such
    if self.parsing_expr:
      p_die("Assignment expression can't be nested like this", token=kw_token)

    self.parsing_expr = True
    try:
      pnode, last_token = self.e_parser.Parse(lexer, start_symbol)
    finally:
      self.parsing_expr = False

    #print_parse_tree = True
    if print_parse_tree:
      self.p_printer.Print(pnode)

    ast_node = self.tr.OilAssign(pnode)
    ast_node.keyword = kw_token  # OilAssign didn't fill this in
    return ast_node, last_token

  def ParseOilArgList(self, lexer, print_parse_tree=False):
    # type: (Lexer, bool) -> Tuple[List[expr_t], token]
    if self.parsing_expr:
      p_die("TODO: can't be nested")

    pnode, last_token = self._ParseOil(lexer, grammar_nt.oil_arglist)

    if print_parse_tree:
      self.p_printer.Print(pnode)

    ast_node = self.tr.ArgList(pnode)
    return ast_node, last_token

  def ParseOilExpr(self, lexer, start_symbol, print_parse_tree=False):
    # type: (Lexer, int, bool) -> Tuple[expr_t, token]
    """For Oil expressions that aren't assignments.  Currently unused."""
    pnode, last_token = self.e_parser.Parse(lexer, start_symbol)

    if print_parse_tree:
      self.p_printer.Print(pnode)

    ast_node = self.tr.Expr(pnode)
    return ast_node, last_token

  def ParseOilForExpr(self, lexer, start_symbol, print_parse_tree=False):
    # type: (Lexer, int, bool) -> Tuple[expr_t, expr_t, token]
    """For Oil expressions that aren't assignments.  Currently unused."""
    pnode, last_token = self.e_parser.Parse(lexer, start_symbol)

    if print_parse_tree:
      self.p_printer.Print(pnode)

    lvalue, iterable = self.tr.OilForExpr(pnode)
    return lvalue, iterable, last_token

  def ParseFuncProc(self, lexer, start_symbol, print_parse_tree=False):
    # type: (Lexer, int, bool) -> Tuple[token, List[param], type_expr_t, token]
    """For Oil expressions that aren't assignments.  Currently unused."""
    pnode, last_token = self.e_parser.Parse(lexer, start_symbol)

    if print_parse_tree:
      self.p_printer.Print(pnode)

    name, params, return_type = self.tr.FuncProc(pnode)
    return name, params, return_type, last_token

  # Another parser instantiation:
  # - For Array Literal in word_parse.py WordParser:
  #   w_parser = WordParser(self.lexer, self.line_reader)
