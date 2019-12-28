"""
Script to generate parts of the API.

* The IDL is used to generate structs, enums and flags.
* The wgpu.h is used to check missing fields, and to  automate enum conversion
  for the rs backend.
* The API classes are written by hand, following the spec. We inject
  some comment lines into the hand-written code to help during dev.

Links:
- Spec and IDL: https://gpuweb.github.io/gpuweb/
- C header: https://github.com/gfx-rs/wgpu/blob/master/ffi/wgpu.h

"""

import os
import subprocess

from wgpu._parsers import IdlParser, HParser


def blacken(src, ll=88):
    p = subprocess.Popen(
        ["black", "-l", str(ll), "-"],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    p.stdin.write(src.encode())
    p.stdin.close()
    result = p.stdout.read().decode()
    log = p.stderr.read().decode()
    if "error" in log.lower():
        raise RuntimeError(log)
    return result


this_dir = os.path.dirname(os.path.abspath(__file__))
lib_dir = os.path.join(this_dir, "wgpu")
resource_dir = os.path.join(lib_dir, "resources")


ip = IdlParser(open(os.path.join(resource_dir, "webgpu.idl"), "rb").read().decode())
ip.parse(verbose=True)

hp = HParser(open(os.path.join(resource_dir, "wgpu.h"), "rb").read().decode())
hp.parse(verbose=True)


# %% Compare

enummap = {}  # name -> int

print("\n##### Comparing flags")
for name in hp.flags:
    if name not in ip.flags:
        print(name, "flag missing in .idl")
for name in ip.flags:
    if name not in hp.flags:
        print(name, "flag missing in .h")
for name in hp.flags:
    if name not in ip.flags:
        continue
    if hp.flags[name] != ip.flags[name]:
        print(" ", name)
        print("c:", ", ".join((f"{key}:{val}" for key, val in hp.flags[name].items())))
        print("i:", ", ".join((f"{key}:{val}" for key, val in ip.flags[name].items())))

# todo: C -> STORAGE_READ:256, INDIRECT:512   IDL -> INDIRECT:256

print("\n##### Comparing enums")
for name in hp.enums:
    if name not in ip.enums:
        print(name, "enum missing in .idl")
for name in ip.enums:
    if name not in hp.enums:
        print(name, "enum missing in .h")
for name in hp.enums:
    if name not in ip.enums:
        continue
    for ikey in ip.enums[name].values():
        hkey = ikey
        hkey = hkey.replace("1d", "D1").replace("2d", "D2").replace("3d", "D3")
        hkey = hkey.replace("-", " ").title().replace(" ", "")
        if hkey in hp.enums[name]:
            enummap[name + "." + ikey] = hp.enums[name][hkey]
        else:
            print(name + "." + ikey, "is missing")

print("\n##### Comparing structs")
for name in hp.structs:
    if name not in ip.structs:
        print(name, "structs missing in .idl")
for name in ip.structs:
    if name not in hp.structs:
        print(name, "structs missing in .h")
for name in hp.structs:
    if name not in ip.structs:
        continue
    keys1 = list(hp.structs[name].keys())
    keys2 = list(ip.structs[name].keys())
    keys3 = {key.lower().replace("_length", "").replace("_", "") for key in keys1}
    keys4 = {key.lower() for key in keys2}
    keys3.discard("todo")
    keys4.discard("label")
    if keys3 != keys4:
        print("  ", name)
        print("c:", keys1)
        print("i:", keys2)


# %% Generate code for flags

print("\n##### Generate API for flags")

preamble = '''
"""
THIS CODE IS AUTOGENERATED - DO NOT EDIT

All wgpu flags. Also available in the root wgpu namespace.
"""


class Flags:

    def __init__(self, name, **kwargs):
        self._name = name
        for key, val in kwargs.items():
            setattr(self, key, val)

    def __iter__(self):
        return iter([key for key in dir(self) if not key.startswith("_")])

    def __repr__(self):
        options = ", ".join(self)
        return f"<{self.__class__.__name__} {self._name}: {options}>"

'''.lstrip()

# Generate code
pylines = [preamble]
pylines.append(f"# %% flags ({len(ip.flags)})\n")
for name, d in ip.flags.items():
    pylines.append(f'{name} = Flags(\n    "{name}",')
    for key, val in d.items():
        pylines.append(f"    {key}={val!r},")
    pylines.append(")\n")

# Write
with open(os.path.join(lib_dir, "flags.py"), "wb") as f:
    code = blacken("\n".join(pylines))
    f.write(code.encode())
print("Written to flags.py")


# %% Generate code for enums

print("\n##### Generate API for enums")

preamble = '''
"""
THIS CODE IS AUTOGENERATED - DO NOT EDIT

All wgpu enums. Also available in the root wgpu namespace.
"""


class Enum:

    def __init__(self, name, **kwargs):
        self._name = name
        for key, val in kwargs.items():
            setattr(self, key, val)

    def __iter__(self):
        return iter(
            [getattr(self, key) for key in dir(self) if not key.startswith("_")]
        )

    def __repr__(self):
        options = ", ".join(f"'{x}'" for x in self)
        return f"<{self.__class__.__name__} {self._name}: {options}>"

'''.lstrip()

# Generate code
pylines = [preamble]
pylines.append(f"# %% Enums ({len(ip.enums)})\n")
for name, d in ip.enums.items():
    pylines.append(f'{name} = Enum(\n    "{name}",')
    for key, val in d.items():
        pylines.append(f'    {key}="{val}",')
    pylines.append(")\n")

# Write
with open(os.path.join(lib_dir, "enums.py"), "wb") as f:
    code = blacken("\n".join(pylines))
    f.write(code.encode())
print("Written to enums.py")


# %% Generate code for e.g. mapping enums

print("\n##### Generate helper code (e.g. mappings)")

preamble = '''
"""
THIS CODE IS AUTOGENERATED - DO NOT EDIT

Mappings that help automate some things in the implementations.
"""
# flake8: noqa
'''.lstrip()

# Generate code
pylines = [preamble]

# pylines.append(f"\n# %% Structs ({len(ip.structs)})\n")
# for name, vals in ip.structs.items():
#     py_args = [field.py_arg() for field in vals.values()]
#     dict_args = [f'"{key}": {key}' for key in vals.keys()]
#     pylines.append(f"def make{name}(*, {', '.join(py_args)}):")
#     the_dict = "{" + ", ".join(dict_args) + "}"
#     pylines.append(f"    return {the_dict}\n")

# pylines.append(f"\n# %% Enum map ({len(enummap)})\n")
pylines.append("enummap = {")
for key, val in enummap.items():
    pylines.append(f'    "{key}": {val!r},')
pylines.append("}\n")

pylines.append("cstructfield2enum = {")
for structname, struct in hp.structs.items():
    for field in struct.values():
        if field.typename.startswith("WGPU"):
            enumname = field.typename[4:]
            if enumname in ip.enums:
                pylines.append(f'    "{structname}.{field.name}": "{enumname}",')
pylines.append("}\n")

# Write
with open(os.path.join(lib_dir, "_mappings.py"), "wb") as f:
    code = blacken("\n".join(pylines))  # just in case; code is already black
    f.write(code.encode())
print("Written to _mappings.py")

# todo: compare backend implementation with classes.py
# todo: some of these checks we may want to run in the tests
# todo: some other stuff we may want to export as a report somewhere


# %% Inject IDL into our hand-written source

# ip.functions["requestAdapter"] = ip.functions.pop("requestadapter")

for fname in ("classes.py", "backend/rs.py"):
    filename = os.path.join(lib_dir, fname)
    print(f"\n##### Check functions in {fname}")

    starts = "# IDL: ", "# wgpu.help("
    with open(filename, "rb") as f:
        code = f.read().decode()
        api_lines = blacken(code, ll=99999999).splitlines()  # inf line lenght
    api_lines = [
        line.rstrip() for line in api_lines if not line.lstrip().startswith(starts)
    ]
    api_lines.append("")

    # Detect api functions
    api_functions = {}
    current_class = None
    for i, line in enumerate(api_lines):
        if line.startswith("class "):
            current_class = line.split(":")[0].split("(")[0].split()[-1]
        if line.lstrip().startswith(("def ", "async def")):
            indent = len(line) - len(line.lstrip())
            funcname = line.split("(")[0].split()[-1]
            if not funcname.startswith("_"):
                if not api_lines[i - 1].lstrip().startswith("@property"):
                    if indent:
                        funcname = current_class + "." + funcname
                    func_id = funcname.replace(".", "").lower()
                    if funcname.startswith("GPU"):
                        func_id = func_id[3:]
                    api_functions[func_id] = funcname, i, indent

    # Inject IDL definitions
    count = 0
    for func_id in reversed(list(api_functions.keys())):
        if func_id in ip.functions:
            funcname, i, indent = api_functions[func_id]
            count += 1
            line = ip.functions[func_id]
            pyline = api_lines[i]
            searches = [func_id]
            args = line.split("(", 1)[1].split(")", 1)[0].split(",")
            argnames = [arg.split("=")[0].split()[-1] for arg in args if arg.strip()]
            argtypes = [arg.split("=")[0].split()[-2] for arg in args if arg.strip()]
            searches.extend([arg[3:] for arg in argtypes if arg.startswith("GPU")])
            searches = [f"'{x}'" for x in searches]

            if len(argtypes) == 1 and argtypes[0].endswith(("Options", "Descriptor")):
                assert argtypes[0].startswith("GPU")
                arg_struct = ip.structs[argtypes[0][3:]]
                py_args = [field.py_arg() for field in arg_struct.values()]
                if py_args[0] == "label: str":
                    py_args[0] = 'label=""'
                if "requestadapter" in func_id:  # todo:  if "." in func_id?
                    py_args = ["*"] + py_args
                else:
                    py_args = ["self", "*"] + py_args
                api_lines[i] = pyline.split("(")[0] + "(" + ", ".join(py_args) + "):"
            else:
                py_args = ["self"] + argnames
                api_lines[i] = pyline.split("(")[0] + "(" + ", ".join(py_args) + "):"
            api_lines[i] += "  # noqa: F821"  # undefined name

            api_lines.insert(i, " " * indent + "# IDL: " + line)
            api_lines.insert(
                i, " " * indent + f"# wgpu.help({', '.join(searches)}, dev=True)"
            )
            if len(api_lines[i]) > 88:
                api_lines[i] += "  # noqa: E501"  # line too long

    # Report missing
    print(f"Found {count} functions already implemented")
    for func_id in ip.functions:
        if func_id not in api_functions:
            print(f"Not implemented: {ip.functions[func_id]}")
    for func_id in api_functions:
        if func_id not in ip.functions:
            funcname = api_functions[func_id][0]
            print(f"Found unknown function {funcname}")

    # Write back
    with open(filename, "wb") as f:
        code = blacken("\n".join(api_lines))
        f.write(code.encode())
    print(f"Injected IDL lines into {fname}")


# >>> [i for i in x if not i.endswith("Descriptor")]
# ['Color', 'Origin2D', 'Origin3D', 'Extent3D', 'RequestAdapterOptions', 'Extensions', 'Limits', 'BindGroupLayoutBinding', 'BindGroupBinding', 'BufferBinding', 'BufferCopyView', 'TextureCopyView', 'ImageBitmapCopyView', 'UncapturedErrorEventInit']
