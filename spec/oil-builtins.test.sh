# Oil builtins

#### repr
x=42
repr x
echo status=$?
repr nonexistent
echo status=$?
## STDOUT:
x = (cell val:(value.Str s:42) exported:F readonly:F)
status=0
'nonexistent' is not defined
status=1
## END

#### repr on indexed array with hole
declare -a array
array[3]=42
repr array
## STDOUT:
array = (cell val:(value.MaybeStrArray strs:[_ _ _ 42]) exported:F readonly:F)
## END


#### push onto a=(1 2)
shopt -s parse_at
a=(1 2)
push :a '3 4' '5'
argv.py @a
## STDOUT:
['1', '2', '3 4', '5']
## END

#### push onto var a = @(1 2)
shopt -s parse_at
var a = @(1 2)
push a '3 4' '5'  # : is optional
argv.py @a
## STDOUT:
['1', '2', '3 4', '5']
## END

#### push with invalid type
s=''
push :s a b
echo status=$?
## stdout: status=1

#### push with invalid var name
push - a b
echo status=$?
## stdout: status=2

#### echo -sep, -end, -n, varying flag syntax
shopt -s all:oil
var a = @('a b' 'c d')
echo @a
echo .
echo -- @a
echo .

echo -sep '' -end '' @a; echo
echo .

echo -sep '_' -- @a
echo -sep '_' -end $' END\n' -- @a

# with =
echo -sep='_' -end=$' END\n' -- @a
# long flags
echo --sep '_' --end $' END\n' -- @a
# long flags with =
echo --sep='_' --end=$' END\n' -- @a

echo -n x
echo -n y
echo

## STDOUT:
a b
c d
.
a b
c d
.
a bc d
.
a b_c d
a b_c d END
a b_c d END
a b_c d END
a b_c d END
xy
## END

#### echo -e not supported
shopt -s all:oil
echo -e foo
echo status=$?
## stdout-json: ""
## status: 2

#### echo syntax error
shopt -s all:oil
echo ---end foo
echo status=$?
## stdout-json: ""
## status: 2

#### echo --
shopt -s all:oil
echo --
# This is annoying
echo -- --
echo done

# this is a syntax error!  Doh.
echo ---
## status: 2
## STDOUT:

--
done
## END
