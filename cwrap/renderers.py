from collections import defaultdict
import os

from cStringIO import StringIO
import cy_ast


UNDEFINED = '__UNDEFINED__'


CODE_HEADER = """\
# This code was automatically generated by CWrap.

"""


class Code(object):

    def __init__(self):
        self._io = StringIO()
        self._indent_level = 0
        self._indentor = '    '
        self._imports = defaultdict(set)
        self._imports_from = defaultdict(lambda: defaultdict(set))
        self._cimports = defaultdict(set)
        self._cimports_from = defaultdict(lambda: defaultdict(set))

    def indent(self, n=1):
        self._indent_level += n

    def dedent(self, n=1):
        self._indent_level -= n

    def write_i(self, code):
        indent = self._indentor * self._indent_level
        self._io.write('%s%s' % (indent, code))

    def write(self, code):
        self._io.write(code)

    def add_import(self, module, as_name=None):
        self._imports[module].add(as_name)

    def add_import_from(self, module, imp_name, as_name=None):
        self._imports_from[module][imp_name].add(as_name)

    def add_cimport(self, module, as_name=None):
        self._cimports[module].add(as_name)
    
    def add_cimport_from(self, module, imp_name, as_name=None):
        if as_name is not None:
            self._cimports_from[module][imp_name].add(as_name)
        else:
            self._cimports_from[module][imp_name]

    def _gen_imports(self):
        import_lines = []

        # cimports
        cimport_items = sorted( self._cimports.iteritems() )
        for module, as_names in cimport_items:
            if as_names:
                for name in sorted(as_names):
                    import_lines.append('cimport %s as %s' % (module, name))
            else:
                import_lines.append('cimport %s' % module)
        
        if import_lines:
            import_lines.append('\n')

        # cimports from
        cimport_from_items = sorted( self._cimports_from.iteritems() )
        for module, impl_dct in cimport_from_items:
            sub_lines = []
            for impl_name, as_names in sorted(impl_dct.iteritems()):
                if as_names:
                    for name in sorted(as_names):
                        sub_lines.append('%s as %s' % (impl_name, name))
                else:
                    sub_lines.append(impl_name)
            sub_txt = ', '.join(sub_lines)
            import_lines.append('from %s cimport %s' % (module, sub_txt))

        if import_lines:
            import_lines.append('\n')

        # cimports
        import_items = sorted( self._imports.iteritems() )
        for module, as_names in import_items:
            if as_names:
                for name in sorted(as_names):
                    import_lines.append('import %s as %s' % (module, name))
            else:
                import_lines.append('import %s' % module)

        if import_lines:
            import_lines.append('\n')

        # cimports from
        import_from_items = sorted( self._imports_from.iteritems() )
        for module, impl_dct in import_from_items:
            sub_lines = []
            for impl_name, as_names in sorted(impl_dct.iteritems()):
                if as_names:
                    for name in sorted(as_names):
                        sub_lines.append('%s as %s' % (impl_name, name))
                else:
                    sub_lines.append(impl_name)
            sub_txt = ', '.join(sub_lines)
            import_lines.append('from %s import %s' % (module, sub_txt))

        return '\n'.join(import_lines)
                    
    def code(self):
        imports = self._gen_imports()
        if imports:
            res = CODE_HEADER + imports + '\n\n' + self._io.getvalue()
        else:
            res = CODE_HEADER + self._io.getvalue()
        return res


class ExternRenderer(object):

    def __init__(self):
        self.node_stack = [None]
        self.code = None
        self.header = None

    def render(self, module_node, header):
        self.node_stack = [None]
        self.code = Code()
        self.header = header

        header_name = header.header_name
        self.code.write_i('cdef extern from "%s":\n\n' % header_name)
        self.code.indent()
        for item in module_node.items:
            if item.location.header_name == header.path:
                self.visit(item)
            else:
                node = item
                if hasattr(node, 'location') and node.location is not None:
                    if node.location.header_name is not None:
                        if node.location.header_name != self.header.path:
                            mod = '_' + os.path.split(node.location.header_name)[-1].rstrip('.h')
                            self.code.add_cimport_from(mod, '*')

        self.code.dedent()

        return self.code.code()
     
    def visit(self, node):
        # add any imports we to reference if the item is defined
        # outside of the current header
        if hasattr(node, 'location') and node.location is not None:
            if node.location.header_name is not None:
                if node.location.header_name != self.header.path:
                    mod = '_' + os.path.split(node.location.header_name)[-1].rstrip('.h')
                    self.code.add_cimport_from(mod, '*')
        self.node_stack.append(node)
        method = 'visit_' + node.__class__.__name__
        visitor = getattr(self, method, self.unhandled_node)
        visitor(node)
        self.node_stack.pop()

    def unhandled_node(self, node):
        print 'Unhandled node in extern renderer: `%s`' % node
    
    def visit_Typedef(self, typedef):
        if isinstance(typedef.typ, (cy_ast.Struct, cy_ast.Enum, cy_ast.Union)):
            self.visit(typedef.typ)
        elif isinstance(typedef.typ, (cy_ast.Pointer, cy_ast.Array)):
            identifier = typedef.identifier
            self.code.write_i('ctypedef ')
            self.visit(typedef.typ)
            self.code.write(' %s\n\n' % identifier)
        elif isinstance(typedef.typ, cy_ast.Typedef):
            identifier = typedef.identifier
            typ_identifier = typedef.typ.identifier
            self.code.write_i('ctypedef %s %s\n\n' % (typ_identifier, identifier))
        elif isinstance(typedef.typ, type) and issubclass(typedef.typ, cy_ast.CType):
            identifier = typedef.identifier
            c_name = typedef.typ.c_name
            self.code.write_i('ctypedef %s %s\n\n' % (c_name, identifier))
        else:
            print 'Unhandled typedef type in extern renderer: `%s`' % typedef.typ

    def visit_Struct(self, struct):
        st_name = struct.identifier
        parent = self.node_stack[-2]
        if isinstance(parent, cy_ast.Typedef):
            td_name = parent.identifier
            if td_name == st_name:
                if struct.opaque:
                    self.code.write_i('cdef struct %s\n' % st_name)
                else:
                    self.code.write_i('cdef struct %s:\n' % st_name)
                    self.code.indent()
                    for field in struct.fields:
                        self.visit(field)
                    self.code.dedent()
            elif st_name is None:
                if struct.opaque:
                    self.code.write_i('ctypedef struct %s\n' % td_name)
                else:
                    self.code.write_i('ctypedef struct %s:\n' % td_name)
                    self.code.indent()
                    for field in struct.fields:
                        self.visit(field)
                    self.code.dedent()
            else:
                if struct.opaque:
                    self.code.write_i('cdef struct %s\n' % st_name)
                else:
                    self.code.write_i('cdef struct %s:\n' % st_name)
                    self.code.indent()
                    for field in struct.fields:
                        self.visit(field)
                    self.code.dedent()
                self.code.write_i('ctypedef %s %s\n' % (st_name, td_name))
        else:
            if struct.opaque:
                self.code.write_i('cdef struct %s\n' % st_name)
            else:
                self.code.write_i('cdef struct %s:\n' % st_name)
                self.code.indent()
                for field in struct.fields:
                    self.visit(field)
                self.code.dedent()
        self.code.write('\n')
    
    def visit_Union(self, union):
        un_name = union.identifier
        parent = self.node_stack[-2]
        if isinstance(parent, cy_ast.Typedef):
            td_name = parent.identifier
            if td_name == un_name:
                if union.opaque:
                    self.code.write_i('cdef union %s\n' % un_name)
                else:
                    self.code.write_i('cdef union %s:\n' % un_name)
                    self.code.indent()
                    for field in union.fields:
                        self.visit(field)
                    self.code.dedent()
            elif un_name is None:
                if union.opaque:
                    self.code.write_i('ctypedef union %s\n' % td_name)
                else:
                    self.code.write_i('ctypedef union %s:\n' % td_name)
                    self.code.indent()
                    for field in union.fields:
                        self.visit(field)
                    self.code.dedent()
            else:
                if union.opaque:
                    self.code.write_i('cdef union %s\n' % un_name)
                else:
                    self.code.write_i('cdef union %s:\n' % un_name)
                    self.code.indent()
                    for field in union.fields:
                        self.visit(field)
                    self.code.dedent()
                self.code.write_i('ctypedef %s %s\n' % (un_name, td_name))
        else:
            if union.opaque:
                self.code.write_i('cdef union %s\n' % un_name)
            else:
                self.code.write_i('cdef union %s:\n' % un_name)
                self.code.indent()
                for field in union.fields:
                    self.visit(field)
                self.code.dedent()
        self.code.write('\n')

    def visit_Field(self, field):
        name = field.identifier
        if isinstance(field.typ, cy_ast.Typedef):
            c_name = field.typ.identifier
        elif isinstance(field.typ, type) and issubclass(field.typ, cy_ast.CType):
            c_name = field.typ.c_name
        elif isinstance(field.typ, (cy_ast.Pointer, cy_ast.Array)):
            c_name, name = self.apply_modifier(field.typ, name)
        else:
            print 'Unhandled field type in extern renderer: `%s`.' % field.typ
            c_name = UNDEFINED
        self.code.write_i('%s %s\n' % (c_name, name))
   
    def visit_Enum(self, enum):
        en_name = enum.identifier
        parent = self.node_stack[-2]
        if isinstance(parent, cy_ast.Typedef):
            td_name = parent.identifier
            if td_name == en_name:
                if enum.opaque:
                    self.code.write_i('cdef enum %s\n' % en_name)
                else:
                    self.code.write_i('cdef enum %s:\n' % en_name)
                    self.code.indent()
                    for field in enum.fields:
                        self.visit(field)
                    self.code.dedent()
            elif en_name is None:
                if enum.opaque:
                    self.code.write_i('ctypedef enum %s\n' % td_name)
                else:
                    self.code.write_i('ctypedef enum %s:\n' % td_name)
                    self.code.indent()
                    for field in enum.fields:
                        self.visit(field)
                    self.code.dedent()
            else:
                if enum.opaque:
                    self.code.write_i('cdef enum %s\n' % en_name)
                else:
                    self.code.write_i('cdef enum %s:\n' % en_name)
                    self.code.indent()
                    for field in enum.fields:
                        self.visit(field)
                    self.code.dedent()
                self.code.write_i('ctypedef %s %s\n' % (en_name, td_name))
        else:
            if enum.opaque:
                if en_name is None:
                    self.code.write_i('cdef enum\n')
                else:
                    self.code.write_i('cdef enum %s\n' % en_name)
            else:
                if en_name is None:
                    self.code.write_i('cdef enum:\n')
                else:
                    self.code.write_i('cdef enum %s:\n' % en_name)
                self.code.indent()
                for field in enum.fields:
                    self.visit(field)
                self.code.dedent()
        self.code.write('\n')
   
    def visit_EnumValue(self, enum_value):
        name = enum_value.identifier
        self.code.write_i('%s\n' % name)
    
    def visit_Function(self, function):
        identifier = function.identifier
        res_type = function.res_type

        if isinstance(res_type, cy_ast.Typedef):
            self.code.write_i('%s ' % res_type.identifier)
        elif isinstance(res_type, type) and issubclass(res_type, cy_ast.CType):
            self.code.write_i('%s ' % res_type.c_name)
        elif isinstance(res_type, cy_ast.Pointer):
            c_name, identifier = self.apply_modifier(res_type, identifier)
            self.code.write_i('%s ' % c_name)
        else:
            print 'undhandled return function type node: `%s`' % res_type
            self.code.write_i('%s\n\n' % UNDEFINED)
            return 
        
        self.code.write('%s(' % identifier)

        if len(function.arguments) == 0:
            print 'Functions with 0 aruguments not handled'
            self.code.write('%s)\n\n' % UNDEFINED)
            return

        if len(function.arguments) == 1:
            if function.arguments[0].typ == cy_ast.Void:
                self.code.write(')\n\n')
                return
        
        for arg in function.arguments[:-1]:
            self.visit(arg)
            self.code.write(', ')
        self.visit(function.arguments[-1])

        self.code.write(')\n\n')

    def visit_Argument(self, argument):
        identifier = argument.identifier
        typ = argument.typ
        if isinstance(typ, cy_ast.Typedef):
            c_name = typ.identifier
        elif isinstance(typ, type) and issubclass(typ, cy_ast.CType):
            c_name = typ.c_name
        elif isinstance(typ, (cy_ast.Pointer, cy_ast.Array)):
            c_name, identifier = self.apply_modifier(typ, identifier)
        else:
            print 'unhandled argument type node: `%s`' % typ
            c_name = UNDEFINED
        self.code.write('%s %s' % (c_name, identifier))

    def visit_Pointer(self, pointer):
        self.visit(pointer.typ)

    def visit_Array(self, array):
        self.visit(array.typ)
        
    def apply_modifier(self, node, name):
        stack = []
        typ = node
        
        while isinstance(typ, (cy_ast.Pointer, cy_ast.Array)):
            stack.append(typ)
            typ = typ.typ
        
        if isinstance(typ, cy_ast.Typedef):
            c_name = typ.identifier
        elif isinstance(typ, type) and issubclass(typ, cy_ast.CType):
            c_name = typ.c_name
        else:
            print 'Unhandled node in apply_notifier: `%s`.' % typ
            return UNDEFINED, UNDEFINED
        
        for i, node in enumerate(stack):
            if i > 0:
                if not isinstance(node, type(stack[i - 1])):
                    name = '(' + name + ')'
            
            if isinstance(node, cy_ast.Pointer):
                name = '*' + name
            elif isinstance(node, cy_ast.Array):
                dim = node.dim
                if dim is None:
                    dim = ''
                name = name + ('[%s]' % dim)  
            else:
                print 'Unhandled node in apply_notifier: `%s`.' % node
                return UNDEFINED, UNDEFINED

        return c_name, name

