#!/usr/bin/python
"""
visitor.py
"""

from asdl import asdl_ as asdl


class AsdlVisitor:
  """Base class for visitors.

  TODO:
  - It might be useful to separate this into VisitChildren() / generic_visit()
    like Python's ast.NodeVisitor  does.
  - Also remove self.f and self.Emit.  Those can go in self.output?
  - Move to common location, since gen_python uses it as well.
  """
  def __init__(self, f):
    self.f = f

  def Emit(self, s, depth, reflow=True):
    for line in FormatLines(s, depth, reflow=reflow):
      self.f.write(line)

  def VisitModule(self, mod):
    for dfn in mod.dfns:
      self.VisitType(dfn)
    self.EmitFooter()

  def VisitType(self, typ, depth=0):
    if isinstance(typ.value, asdl.Sum):
      self.VisitSum(typ.value, typ.name, depth)
    elif isinstance(typ.value, asdl.Product):
      self.VisitProduct(typ.value, typ.name, depth)
    else:
      raise AssertionError(typ)

  def VisitSum(self, sum, name, depth):
    if asdl.is_simple(sum):
      self.VisitSimpleSum(sum, name, depth)
    else:
      self.VisitCompoundSum(sum, name, depth)

  # Optionally overridden.
  def VisitProduct(self, value, name, depth):
    pass
  def VisitSimpleSum(self, value, name, depth):
    pass
  def VisitCompoundSum(self, value, name, depth):
    pass
  def EmitFooter(self):
    pass


TABSIZE = 2
MAX_COL = 80

# Copied from asdl_c.py

def _ReflowLines(s, depth):
  """Reflow the line s indented depth tabs.

  Return a sequence of lines where no line extends beyond MAX_COL when properly
  indented.  The first line is properly indented based exclusively on depth *
  TABSIZE.  All following lines -- these are the reflowed lines generated by
  this function -- start at the same column as the first character beyond the
  opening { in the first line.
  """
  size = MAX_COL - depth * TABSIZE
  if len(s) < size:
    return [s]

  lines = []
  cur = s
  padding = ""
  while len(cur) > size:
    i = cur.rfind(' ', 0, size)
    # XXX this should be fixed for real
    if i == -1 and 'GeneratorExp' in cur:
      i = size + 3
    assert i != -1, "Impossible line %d to reflow: %r" % (size, s)
    lines.append(padding + cur[:i])
    if len(lines) == 1:
      # find new size based on brace
      j = cur.find('{', 0, i)
      if j >= 0:
        j += 2  # account for the brace and the space after it
        size -= j
        padding = " " * j
      else:
        j = cur.find('(', 0, i)
        if j >= 0:
          j += 1  # account for the paren (no space after it)
          size -= j
          padding = " " * j
    cur = cur[i + 1:]
  else:
    lines.append(padding + cur)
  return lines


def FormatLines(s, depth, reflow=True):
  """Make the generated code readable.

  Args:
    depth: controls indentation
    reflow: line wrapping.
  """
  if reflow:
    lines = _ReflowLines(s, depth)
  else:
    lines = [s]

  result = []
  for line in lines:
    line = (" " * TABSIZE * depth) + line + "\n"
    result.append(line)
  return result
