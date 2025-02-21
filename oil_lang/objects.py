#!/usr/bin/env python2
"""
objects.py

Python types under value.Obj.  See the invariant in osh/runtime.asdl.
"""
from __future__ import print_function

# These are for data frames?

class BoolArray(list):
  """
  var b = @[true false false]
  var b = @[T F F]
  """
  pass

class IntArray(list):
  """
  var b = @[1 2 3 -42]
  """
  pass


class FloatArray(list):
  """
  var b = @[1.1 2.2 3.9]
  """
  pass


class StrArray(list):
  """
  local oldarray=(a b c)  # only strings, but deprecated

  var array = @(a b c)  # only strings, PARSED like shell
  var oilarray = @[a b c]  # can be integers

  TODO: value.MaybeStrArray should be renamed LooseArray?
    Because it can have holes!
    StrNoneArray?  MaybeMaybeStrArray?

  In C, do both of them have the same physical representation?
  """
  pass


class Func(object):
  """An Oil function declared with 'func'."""
  def __init__(self, node, default_vals, ex):
    self.node = node
    self.default_vals = default_vals
    self.ex = ex

  def __call__(self, *args, **kwargs):
    return self.ex.RunOilFunc(self.node, self.default_vals, args, kwargs)


class Proc(object):
  """An Oil proc declared with 'proc'.

  Unlike a shell proc, it has a signature, so we need to bind names to params.
  """
  def __init__(self, node):
    self.docstring = ''
    self.node = node


class Module(object):
  """An Oil module.

  The 'use' keyword creates an object of this type in the current namespace.

  It holds both variables and functions.

  But it doesn't have "$@" or anything else that Mem has?
  Mem also has introspection.  For function calls and such.
  Maybe that only applies to 'proc' and not 'func'.
  """
  def __init__(self, name):
    self.name = name
    self.docstring = ''
    # items
    self.attrs = {}
