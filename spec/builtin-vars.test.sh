#!/usr/bin/env bash
#
# Tests for builtins having to do with variables: export, readonly, unset, etc.
#
# Also see assign.test.sh.

#### Export sets a global variable
# Even after you do export -n, it still exists.
f() { export GLOBAL=X; }
f
echo $GLOBAL
printenv.py GLOBAL
## STDOUT:
X
X
## END

#### Export sets a global variable that persists after export -n
f() { export GLOBAL=X; }
f
echo $GLOBAL
printenv.py GLOBAL
export -n GLOBAL
echo $GLOBAL
printenv.py GLOBAL
## STDOUT: 
X
X
X
None
## END
## N-I mksh/dash STDOUT:
X
X
## END
## N-I mksh status: 1
## N-I dash status: 2
## N-I zsh STDOUT:
X
X
X
X
## END

#### export -n undefined is ignored
set -o errexit
export -n undef
echo status=$?
## stdout: status=0
## N-I mksh/dash/zsh stdout-json: ""
## N-I mksh status: 1
## N-I dash status: 2
## N-I zsh status: 1

#### export -n foo=bar not allowed
foo=old
export -n foo=new
echo status=$?
echo $foo
## STDOUT:
status=2
old
## END
## OK bash STDOUT:
status=0
new
## END
## N-I zsh STDOUT:
status=1
old
## END
## N-I dash status: 2
## N-I dash stdout-json: ""
## N-I mksh status: 1
## N-I mksh stdout-json: ""

#### Export a global variable and unset it
f() { export GLOBAL=X; }
f
echo $GLOBAL
printenv.py GLOBAL
unset GLOBAL
echo g=$GLOBAL
printenv.py GLOBAL
## STDOUT: 
X
X
g=
None
## END

#### Export existing global variables
G1=g1
G2=g2
export G1 G2
printenv.py G1 G2
## STDOUT: 
g1
g2
## END

#### Export existing local variable
f() {
  local L1=local1
  export L1
  printenv.py L1
}
f
printenv.py L1
## STDOUT: 
local1
None
## END

#### Export a local that shadows a global
V=global
f() {
  local V=local1
  export V
  printenv.py V
}
f
printenv.py V  # exported local out of scope; global isn't exported yet
export V
printenv.py V  # now it's exported
## STDOUT: 
local1
None
global
## END

#### Export a variable before defining it
export U
U=u
printenv.py U
## stdout: u

#### Unset exported variable, then define it again.  It's NOT still exported.
export U
U=u
printenv.py U
unset U
printenv.py U
U=newvalue
echo $U
printenv.py U
## STDOUT:
u
None
newvalue
None
## END

#### Exporting a parent func variable (dynamic scope)
# The algorithm is to walk up the stack and export that one.
inner() {
  export outer_var
  echo "inner: $outer_var"
  printenv.py outer_var
}
outer() {
  local outer_var=X
  echo "before inner"
  printenv.py outer_var
  inner
  echo "after inner"
  printenv.py outer_var
}
outer
## STDOUT:
before inner
None
inner: X
X
after inner
X
## END

#### Dependent export setting
# FOO is not respected here either.
export FOO=foo v=$(printenv.py FOO)
echo "v=$v"
## stdout: v=None

#### Exporting a variable doesn't change it
old=$PATH
export PATH
new=$PATH
test "$old" = "$new" && echo "not changed"
## stdout: not changed

#### can't export array
typeset -a a
a=(1 2 3)
export a
printenv.py a
## STDOUT:
None
## END
## BUG mksh STDOUT:
1
## END
## N-I dash status: 2
## N-I dash stdout-json: ""
## OK osh status: 1
## OK osh stdout-json: ""

#### can't export associative array
typeset -A a
a["foo"]=bar
export a
printenv.py a
## STDOUT:
None
## END
## N-I mksh status: 1
## N-I mksh stdout-json: ""
## OK osh status: 1
## OK osh stdout-json: ""

#### assign to readonly variable
# bash doesn't abort unless errexit!
readonly foo=bar
foo=eggs
echo "status=$?"  # nothing happens
## status: 1
## BUG bash stdout: status=1
## BUG bash status: 0
## OK dash/mksh status: 2

#### Make an existing local variable readonly
f() {
	local x=local
	readonly x
	echo $x
	eval 'x=bar'  # Wrap in eval so it's not fatal
	echo status=$?
}
x=global
f
echo $x
## STDOUT:
local
status=1
global
## END
## OK dash STDOUT:
local
## END
## OK dash status: 2

# mksh aborts the function, weird
## OK mksh STDOUT:
local
global
## END

#### assign to readonly variable - errexit
set -o errexit
readonly foo=bar
foo=eggs
echo "status=$?"  # nothing happens
## status: 1
## OK dash/mksh status: 2

#### Unset a variable
foo=bar
echo foo=$foo
unset foo
echo foo=$foo
## STDOUT:
foo=bar
foo=
## END

#### Unset exit status
V=123
unset V
echo status=$?
## stdout: status=0

#### Unset nonexistent variable
unset ZZZ
echo status=$?
## stdout: status=0

#### Unset readonly variable
# dash and zsh abort the whole program.   OSH doesn't?
readonly R=foo
unset R
echo status=$?
## status: 0
## stdout: status=1
## OK dash status: 2
## OK dash stdout-json: ""
## OK zsh status: 1
## OK zsh stdout-json: ""

#### Unset a function without -f
f() {
  echo foo
}
f
unset f
f
## stdout: foo
## status: 127
## N-I dash/mksh/zsh status: 0
## N-I dash/mksh/zsh STDOUT:
foo
foo
## END

#### Unset has dynamic scope
f() {
  unset foo
}
foo=bar
echo foo=$foo
f
echo foo=$foo
## STDOUT:
foo=bar
foo=
## END

#### Unset invalid variable name
unset %
echo status=$?
## STDOUT:
status=2
## END
## OK bash/mksh STDOUT:
status=1
## END
## BUG zsh STDOUT:
status=0
## END
# dash does a hard failure!
## OK dash stdout-json: ""
## OK dash status: 2

#### Unset nonexistent variable
unset _nonexistent__
echo status=$?
## STDOUT:
status=0
## END

#### Unset -v
foo() {
  echo "function foo"
}
foo=bar
unset -v foo
echo foo=$foo
foo
## STDOUT: 
foo=
function foo
## END

#### Unset -f
foo() {
  echo "function foo"
}
foo=bar
unset -f foo
echo foo=$foo
foo
echo status=$?
## STDOUT: 
foo=bar
status=127
## END

#### Unset array member
a=(x y z)
unset 'a[1]'
echo status=$?
echo "${a[@]}" len="${#a[@]}"
## STDOUT:
status=0
x z len=2
## END
## N-I dash status: 2
## N-I dash stdout-json: ""
## OK zsh STDOUT:
status=0
 y z len=3
## END
## N-I osh STDOUT:
status=2
x y z len=3
## END

#### Unset array member with expression
i=1
a=(w x y z)
unset 'a[ i - 1 ]' a[i+1]  # note: can't have space between a and [
echo status=$?
echo "${a[@]}" len="${#a[@]}"
## STDOUT:
status=0
x z len=2
## END
## N-I dash status: 2
## N-I dash stdout-json: ""
## N-I zsh status: 1
## N-I zsh stdout-json: ""
## N-I osh STDOUT:
status=2
w x y z len=4
## END

#### Use local twice
f() {
  local foo=bar
  local foo
  echo $foo
}
f
## stdout: bar
## BUG zsh STDOUT:
foo=bar
bar
## END

#### Local without variable is still unset!
set -o nounset
f() {
  local foo
  echo "[$foo]"
}
f
## stdout-json: ""
## status: 1
## OK dash status: 2
# zsh doesn't support nounset?
## BUG zsh stdout: []
## BUG zsh status: 0

#### local after readonly
f() { 
  readonly y
  local x=1 y=$(( x ))
  echo y=$y
}
f
## stdout-json: ""
## status: 1
## OK dash status: 2
## BUG bash stdout: y=
## BUG bash status: 0
## BUG mksh stdout: y=0
## BUG mksh status: 0

