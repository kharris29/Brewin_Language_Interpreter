import copy
from brewparse import parse_program
from intbase import ErrorType, InterpreterBase
from type_valuev1 import Type, Value, create_value, get_printable

class Interpreter(InterpreterBase):
    NIL_VALUE = create_value(InterpreterBase.NIL_DEF)
    LAMBDA_NODE = 0
    CAPTURED_VARS = 1

    # Initialize interpreter
    def __init__(self, console_output=True, inp=None, trace_output=False):
        super().__init__(console_output, inp) # call InterpreterBase's constructor
        self.trace_output = trace_output

    # Parse the program to get the AST and run the main function
    def run(self, program):
        ast = parse_program(program)
        self.ast = ast
        self.get_debug_info(ast)
        main_node = self.get_main_node(ast) 
        self.variable_scope_list = [{}]
        self.variable_alias_list = [{}]
        self.run_func(main_node)
        
    # Get main function node
    def get_main_node(self, ast):
        functions_list = ast.dict['functions']
        if functions_list:
            for elem in functions_list:
                if elem.dict['name'] == 'main':
                    return elem
        super().error(
            ErrorType.NAME_ERROR,
            "No main() function was found",
        )

    # Run statements within if/else blocks
    def run_if_statements(self, func_node):
        statements = func_node.dict.get('statements')      
        return_value = None

        for statement_node in statements:
            temp_return_val = self.run_statement(statement_node)
            if temp_return_val is not None:
                return_value = temp_return_val
                break

        # Delete outermost scope once function is done executing
        self.variable_scope_list.pop()
        return return_value

    # Run statements within function blocks
    def run_func(self, func_node, lambda_node = None):
        statements = func_node.dict.get('statements')     
        return_value = Interpreter.NIL_VALUE

        for statement_node in statements:
            temp_return_val = self.run_statement(statement_node, lambda_node)            
            if temp_return_val is not None:
                return_value = temp_return_val
                break

        # Delete outermost scope once function is done executing
        self.variable_scope_list.pop()
        self.variable_alias_list.pop()
        return return_value

    # Process Statement nodes depending on their type
    # Statement node types include =, fcall, mcall, return, if, & while
    def run_statement(self, statement_node, lambda_node = None):
        if statement_node.elem_type == "=":
            self.do_assignment(statement_node, lambda_node)
        elif statement_node.elem_type == "fcall" or statement_node.elem_type == "mcall":
            self.do_func_call(statement_node, lambda_node) 
        elif statement_node.elem_type == 'return':       
            source_node = statement_node.dict['expression']
            if source_node is None:
                return Interpreter.NIL_VALUE
            else:
                return copy.deepcopy(self.evaluate_expression(source_node, lambda_node))
        elif statement_node.elem_type == "if":
            condition = self.evaluate_expression(statement_node.dict['condition'])

            if condition.type() == Type.INT:
                condition = Value(Type.BOOL, self.get_bool_from_int(condition.v))

            elif condition.type() != Type.BOOL:
                super().error(
                    ErrorType.TYPE_ERROR,
                    "If condition does not evaluate to a boolean",
                )

            # Run statements in "if" block
            if condition.v: 
                # Create new scope for block
                self.variable_scope_list.append({})
                self.variable_alias_list.append({})

                return self.run_if_statements(statement_node) # this function handles popping the outermost scope
            # Run statements in "else" block
            elif statement_node.dict['else_statements'] is not None:
                # Create new scope for block
                self.variable_scope_list.append({})
                self.variable_alias_list.append({})

                updated_statement_node = copy.deepcopy(statement_node)
                updated_statement_node.dict['statements'] = statement_node.dict['else_statements']
                return self.run_if_statements(updated_statement_node) # this function handles popping the outermost scope
        elif statement_node.elem_type == "while":
            condition = self.evaluate_expression(statement_node.dict['condition'])
            if condition.type() == Type.INT:
                condition = Value(Type.BOOL, self.get_bool_from_int(condition.v))

            elif condition.type() != Type.BOOL:
                super().error(
                    ErrorType.TYPE_ERROR,
                    "If condition does not evaluate to a boolean",
                )
         
            # While the condition is true, run the statements inside.
            # If one of the statements inside has a return value,
            # that means we called return within the loop and we want to break out of the loop,
            # returning whatever that value was
            return_value = None

            while (condition.v):
                # Create new scope for block
                self.variable_scope_list.append({})
                self.variable_alias_list.append({})

                for statement in statement_node.get('statements'):
                    temp_return_val = self.run_statement(statement)
                    if temp_return_val is not None:
                        return_value = temp_return_val
                        break # Break from for loop
                
                # Return occured within while loop, so return that value
                if return_value is not None:
                    self.variable_scope_list.pop()
                    return return_value
                
                # Otherwise, one iteration ran to completion
                # Delete the outermost scope
                self.variable_scope_list.pop()

                # Update condition and verify it still evaluates to bool
                # (It could not evaluate to bool if, for instance, it uses a var whose type gets changed)
                condition = self.evaluate_expression(statement_node.dict['condition'])

                if condition.type() == Type.INT:
                    condition = Value(Type.BOOL, self.get_bool_from_int(condition.v))
                elif condition.type() != Type.BOOL:
                    super().error(
                        ErrorType.TYPE_ERROR,
                        "While condition does not evaluate to a boolean",
                    )

        return None

    # Assign a value to a variable 
    # Including within a lambda or object
    # Handles pass by reference if applicable 
    def do_assignment(self, statement_node, lambda_node = None):
        target_var_name = statement_node.dict['name']
        source_node = statement_node.dict['expression']
        resulting_value = self.evaluate_expression(source_node, lambda_node)

        # Assignment occurs within a lambda function
        if lambda_node is not None:
            captured_vars_dict = lambda_node[Interpreter.CAPTURED_VARS]
            # Assign a value to a variable previously captured by the lambda function
            if target_var_name in captured_vars_dict:
                captured_vars_dict[target_var_name] = resulting_value
                return
                
        # Assignment to an object's fields or methods
        if '.' in target_var_name:
            split_names = target_var_name.split('.')
            obj_name = split_names[0] # Get the object's name (before .)
            field_name = split_names[1] # Get the object's field/method (after .)

            # If assigning one object's "proto" field to be another object,
            # validate the latter is actually an object type
            if field_name == 'proto' and (resulting_value.type() != Type.OBJ and resulting_value.type() != Type.NIL):
                super().error(
                    ErrorType.TYPE_ERROR,
                    "Can't set proto to non-object or non-nil type",
                )
                    
            # Validate variable exists
            closest_scope_index = self.validate_var_name(obj_name)
            if closest_scope_index is None:
                # Attempting to assign a value to an object that hasn't been created
                super().error(
                    ErrorType.NAME_ERROR,
                    "Object not found",
                )
            else:
                # Validate object type
                if (self.variable_scope_list[closest_scope_index][obj_name].type() != Type.OBJ):
                    super().error(
                        ErrorType.TYPE_ERROR,
                        "Attempting to get field/method from non-object type",
                    )
                
                # Update object's field or method
                self.variable_scope_list[closest_scope_index][obj_name].v[field_name] = resulting_value
                                
                return

        # Assignment to a variable 
            
        # Check all scopes to see if the variable exists 
        # If it does, update that value (dynamic scoping)
        # Otherwise, create a new variable by inserting into the outermost scope
            
        closest_scope_index = None
        # Iterate through the scopes to see if the variable name exists
        for i in range(len(self.variable_scope_list)-1, -1, -1):
            curr_scope_dict = self.variable_scope_list[i]
            if target_var_name in curr_scope_dict:
                closest_scope_index = i
                break

        # Variable doesn't exist, so insert the variable into outermost scope
        if closest_scope_index is None:
            self.variable_scope_list[len(self.variable_scope_list)-1][target_var_name] = resulting_value
        # Variable does exist, so update value of the variable in the relevant scope
        else:
            self.variable_scope_list[closest_scope_index][target_var_name] = resulting_value
            
            # Handle pass by reference (cascading upwards in the event of nested references)
            # Example
                # Say that var c is passed by reference into a function using the var b
                # func call: func(c);       func declaration: func(ref b) { b = a; }
                # now b references a, but because b references c, c should reference a too
                # (a is resulting_value, b is target_var_name, c is ref_var_name)
            while target_var_name in self.variable_alias_list[closest_scope_index]:
                ref_var_name = self.variable_alias_list[closest_scope_index][target_var_name]
                self.variable_scope_list[closest_scope_index-1][ref_var_name] = resulting_value

                closest_scope_index -= 1
                target_var_name = ref_var_name

    # Returns boolean indicating if an operator is a binary operator
    def is_binary_op(self, node_elem_type):
        if node_elem_type == '+' or node_elem_type == '-' or node_elem_type == '*' or node_elem_type == '/' or node_elem_type == '<' or node_elem_type == '<=' or node_elem_type == '>' or node_elem_type == '>=':
            return True
        return False
    
    # Get boolean Value object
    def get_bool_value(self, bool):
        if bool:
            return create_value("true")
        return create_value("false")
    
    # Get boolean Value object from an integer value
    def get_bool_from_int(self, int_val):
        if int_val != 0:
            return True
        return False

    # Get integer Value object from a boolean value
    def get_int_from_bool(self, bool_val):
        if bool_val:
            return 1
        return 0

    # Evaluate expression based on its elem_type (int, string, various operators, etc.)
    # Returns Value object
    def evaluate_expression(self, source_node, lambda_node = None):
        # Return new Object Value node with empty fields
        if source_node.elem_type == '@':
            obj_fields = {}
            return Value(Type.OBJ, obj_fields)

        # Return Int/String/Bool/Nil Value Nodes
        if source_node.elem_type == 'int' or source_node.elem_type == 'string':
            # Handles edge case where the elem_type is 'string' and value is 'true' or 'false'
            # (create_value function mistakenly assigns creates a node of type Bool)
            if source_node.elem_type == 'string' and (source_node.dict['val'] == 'true' or source_node.dict['val'] == 'false'):
                return Value(Type.STRING, source_node.dict['val'])
            # Similar situation with 'nil'
            if source_node.elem_type == 'string' and source_node.dict['val'] == 'nil':
                 return Value(Type.STRING, source_node.dict['val'])
            
            return create_value(source_node.dict['val'])
        elif source_node.elem_type == 'bool':
            return self.get_bool_value(source_node.dict['val'])
        elif source_node.elem_type == 'nil':
            return create_value('nil')

        # Return Value Nodes from variables
        elif source_node.elem_type == 'var':
            var_name = source_node.dict['name']

            # Get value captured by lambda (including nested lambdas)
            if lambda_node is not None:
                captured_vars_dict = lambda_node[Interpreter.CAPTURED_VARS]
                for key, value in captured_vars_dict.items(): # var name : value
                    if var_name == key:
                        return value
                    if value.type() == Type.LAMBDA:
                        lambda_dict = value.v[Interpreter.CAPTURED_VARS]
                        for key2, value2 in lambda_dict.items():
                            if var_name == key2:
                                return value2
                   
            # Function Value nodes
            functions_list = self.ast.dict['functions']
            if functions_list:
                # Validate the function has not been overloaded
                func_match_count = 0 # should be only 1
                matched_elem = None
                for elem in functions_list:
                    if elem.dict['name'] == var_name:
                        func_match_count += 1
                        matched_elem = elem

                if func_match_count == 1 and matched_elem is not None:
                    return Value(Type.FUNC, matched_elem) # matched_elem = statement node
                elif func_match_count > 1:
                    super().error(
                        ErrorType.NAME_ERROR,
                        f"Function {var_name} has been overloaded, so it can't be assigned to a variable",
                    )

            # Get Value node (field/method) from Object variable
            if '.' in var_name:
                split_names = var_name.split('.')
                obj_name = split_names[0] # Get the object's name (before .)
                field_name = split_names[1] # Get the object's field/method (after .)
        
                # Validate variable exists
                closest_scope_index = self.validate_var_name(obj_name)
                if closest_scope_index is None:
                    # Attempting to assign a value to an object that hasn't been created
                    super().error(
                        ErrorType.NAME_ERROR,
                        "Object not found",
                    )
                else:
                    # Validate object type
                    if (self.variable_scope_list[closest_scope_index][obj_name].type() != Type.OBJ):
                            super().error(
                                ErrorType.TYPE_ERROR,
                                "Attempting to get field/method from non-object type",
                            )

                    obj_fields_dict = self.variable_scope_list[closest_scope_index][obj_name].v
                    # If field/method belongs to object, return it
                    if field_name in obj_fields_dict:
                        return obj_fields_dict[field_name]
                    # If field/method not directly on object, see if it belongs to the object's prototype
                    # (accounting for chained prototypes)
                    else:
                        while (True):
                            if 'proto' in obj_fields_dict:
                                obj = obj_fields_dict['proto']

                                if (obj.type() != Type.OBJ):
                                    break

                                obj_fields_dict = obj.v
                                if field_name in obj_fields_dict:
                                    return obj_fields_dict[field_name]
                            else:
                                break

                        # Validate field exists on the object
                        super().error(
                            ErrorType.NAME_ERROR,
                            "Field does not exist on this object",
                        )

            # Get Value node from variable
                        
            scope_index = self.validate_var_name(var_name)
            if scope_index is not None:
                # If this variable references another variable, make sure its value is up to date, then return it
                if var_name in self.variable_alias_list[scope_index]:
                    # When we update variables in assignment, we use a bottom-up approach
                    # Example -
                        # say a and b reference d and e respectively. d and e both reference f
                        # let a now reference c. so, d references c. and f references c.
                        # but b and e should also reference c...
                    # We implement a top-down approach to catch the out-of-date reference variables
                        # We find the top-most variable, in this case, f
                        # and then we update all variables which directly/indirectly reference f
                        # in this case, b and e, but not forgetting references to b and e, and so on

                    ref_var_name = self.variable_alias_list[scope_index][var_name]

                    # Get top-most reference variable
                    top_most_var_name = var_name
                    search_scope_index = scope_index
                    while top_most_var_name in self.variable_alias_list[search_scope_index]:
                        top_most_var_name = self.variable_alias_list[search_scope_index][top_most_var_name]
                        search_scope_index -= 1 # innermost scope is the beginning of the list, outermost scope is at the end

                    # Now cascade the changes down,
                    # updating all variables that reference the top-most reference variable
                    # and variables that reference *those* references, and so on
                    scope_index_update_ref = search_scope_index + 1
                    try:
                        new_value = self.variable_scope_list[search_scope_index][top_most_var_name]
                    except:
                        return self.variable_scope_list[scope_index][var_name]
                        
                    referenced_var_names = [top_most_var_name] # list of variables that directly/indirectly reference the top-most variable
                    while scope_index_update_ref < len(self.variable_scope_list):
                        new_referenced_var_names = []
                        for key, val in self.variable_alias_list[scope_index_update_ref].items():
                            if val in referenced_var_names:
                                self.variable_scope_list[scope_index_update_ref][key] = new_value 
                                new_referenced_var_names.append(key)
                        referenced_var_names = new_referenced_var_names
                        scope_index_update_ref += 1
                            
                    self.variable_scope_list[scope_index][var_name] = self.variable_scope_list[scope_index-1][ref_var_name]
                    return self.variable_scope_list[scope_index][var_name]
                
                return self.variable_scope_list[scope_index][var_name]
        
        # Return Value node from Binary/Comparison Operators for Ints or Strings
        elif self.is_binary_op(source_node.elem_type):
            op1_val = self.evaluate_expression(source_node.dict['op1'], lambda_node)
            op2_val = self.evaluate_expression(source_node.dict['op2'], lambda_node)
   
            # String concatenation
            if (source_node.elem_type == '+' and op1_val.type() == Type.STRING and op2_val.type() == Type.STRING):
                return create_value(op1_val.v + op2_val.v)

            if (op1_val.type() == Type.BOOL):
                op1_val = Value(Type.INT, self.get_int_from_bool(op1_val.v))
            if (op2_val.type() == Type.BOOL):
                op2_val = Value(Type.INT, self.get_int_from_bool(op2_val.v))

            if (op1_val.type() != Type.INT or op2_val.type() != Type.INT):
                super().error(
                    ErrorType.TYPE_ERROR,
                    "Incompatible types for arithmetic operation",
                )
            
            if source_node.elem_type == '+':
                return create_value(op1_val.v + op2_val.v)
            elif source_node.elem_type == '-':
                return create_value(op1_val.v - op2_val.v)
            elif source_node.elem_type == '*':
                return create_value(op1_val.v * op2_val.v)
            elif source_node.elem_type == '/':
                return create_value(op1_val.v // op2_val.v)
            elif source_node.elem_type == '<':
                return self.get_bool_value(op1_val.v < op2_val.v)
            elif source_node.elem_type == '<=':
                return self.get_bool_value(op1_val.v <= op2_val.v)
            elif source_node.elem_type == '>':
                return self.get_bool_value(op1_val.v > op2_val.v)
            elif source_node.elem_type == '>=':
                return self.get_bool_value(op1_val.v >= op2_val.v)

        # Return Value node from Arithmetic Negation
        elif source_node.elem_type == 'neg':
            op1_val = self.evaluate_expression(source_node.dict['op1'], lambda_node)

            if (op1_val.type() != Type.INT):
                super().error(
                    ErrorType.TYPE_ERROR,
                    "Incompatible type for arithmetic negation",
                )

            return create_value(op1_val.v * (-1))
        
        # Return Value node from Boolean Binary Operators
        elif source_node.elem_type == '&&' or source_node.elem_type == '||':
            op1_val = self.evaluate_expression(source_node.dict['op1'], lambda_node)
            op2_val = self.evaluate_expression(source_node.dict['op2'], lambda_node)

            if (op1_val.type() == Type.INT):
                op1_val = Value(Type.BOOL, self.get_bool_from_int(op1_val.v))
            if (op2_val.type() == Type.INT):
                op2_val = Value(Type.BOOL, self.get_bool_from_int(op2_val.v))

            if (op1_val.type() != Type.BOOL or op2_val.type() != Type.BOOL):
                super().error(
                    ErrorType.TYPE_ERROR,
                    "Incompatible types for boolean operation",
                )

            if source_node.elem_type == '&&':
                return self.get_bool_value(op1_val.v and op2_val.v)            
            elif source_node.elem_type == '||':
                return self.get_bool_value(op1_val.v or op2_val.v)

        # Return Value node from Boolean Negation
        elif source_node.elem_type == '!':
            op1_val = self.evaluate_expression(source_node.dict['op1'], lambda_node)

            if (op1_val.type() == Type.INT):
                op1_val = Value(Type.BOOL, self.get_bool_from_int(op1_val.v))
                
            if (op1_val.type() != Type.BOOL):
                super().error(
                    ErrorType.TYPE_ERROR,
                    "Incompatible type for boolean negation",
                )

            return self.get_bool_value(not op1_val.v)

        # Return Value node from Comparison Operators
        elif source_node.elem_type == '==' or source_node.elem_type == '!=':
            op1_val = self.evaluate_expression(source_node.dict['op1'], lambda_node)
            op2_val = self.evaluate_expression(source_node.dict['op2'], lambda_node)

            if op1_val.type() == Type.LAMBDA and op2_val.type() == Type.LAMBDA:
                if source_node.elem_type == '==':
                    return self.get_bool_value(op1_val is op2_val)
                elif source_node.elem_type == '!=':
                    return self.get_bool_value(op1_val is not op2_val)
                
            if op1_val.type() == Type.OBJ and op2_val.type() == Type.OBJ:
                if source_node.elem_type == '==':
                    return self.get_bool_value(op1_val is op2_val)
                elif source_node.elem_type == '!=':
                    return self.get_bool_value(op1_val is not op2_val)
            
            if ((op1_val.type() == Type.STRING and op2_val.type() == Type.STRING) or (op1_val.type() == Type.INT and op2_val.type() == Type.INT) or (op1_val.type() == Type.BOOL and op2_val.type() == Type.BOOL)):
                if source_node.elem_type == '==':
                    return self.get_bool_value(op1_val.v == op2_val.v)
                elif source_node.elem_type == '!=':
                    return self.get_bool_value(op1_val.v != op2_val.v)
                
            elif (op1_val.type() == Type.BOOL and op2_val.type() == Type.INT) or (op1_val.type() == Type.INT and op2_val.type() == Type.BOOL):
                if op1_val.type() == Type.INT:
                    op1_bool = self.get_bool_from_int(op1_val.v)
                    if source_node.elem_type == '==':
                        return self.get_bool_value(op1_bool == op2_val.v)
                    elif source_node.elem_type == '!=':
                        return self.get_bool_value(op1_bool != op2_val.v)
                    
                if op2_val.type() == Type.INT:
                    op2_bool = self.get_bool_from_int(op2_val.v)
                    if source_node.elem_type == '==':
                        return self.get_bool_value(op1_val.v == op2_bool)
                    elif source_node.elem_type == '!=':
                        return self.get_bool_value(op1_val.v != op2_bool)

            elif op1_val.type() == Type.NIL and op2_val.type() == Type.NIL:
                if source_node.elem_type == '==':
                    return self.get_bool_value(True)
                elif source_node.elem_type == '!=':
                    return self.get_bool_value(False)
                
            elif op1_val.type() == Type.FUNC and op2_val.type() == Type.FUNC:
                if source_node.elem_type == '==':
                    return self.get_bool_value(op1_val.v is op2_val.v)
                elif source_node.elem_type == '!=':
                    return self.get_bool_value(op1_val.v is not op2_val.v)
            else: 
                if source_node.elem_type == '==':
                    return self.get_bool_value(False)
                elif source_node.elem_type == '!=':
                    return self.get_bool_value(True)
    
        # Return Value node from 'inputi' function 
        elif ('name' in source_node.dict and source_node.dict['name'] == 'inputi'):
            args = source_node.dict['args']
            if args:
                # Validate there is not more than one param to inputi
                if len(args) > 1:
                    super().error(
                    ErrorType.NAME_ERROR,
                    f"inputi() function found that takes > 1 parameter",
                    )
                arg_value = self.evaluate_expression(source_node.dict['args'][0], lambda_node)
                super().output(get_printable(arg_value)) 
        
            user_input = super().get_input()
            if not user_input.isdigit():
                super().error(
                    ErrorType.TYPE_ERROR,
                    "Input was not integer",
                )
            return create_value(int(user_input))

        # Return Value node from 'inputs' function
        elif ('name' in source_node.dict and source_node.dict['name'] == 'inputs'):
            args = source_node.dict['args']
            if args:
                # Validate there is not more than one param to inputs
                if len(args) > 1:
                    super().error(
                    ErrorType.NAME_ERROR,
                    f"inputs() function found that takes > 1 parameter",
                    )
                arg_value = self.evaluate_expression(source_node.dict['args'][0], lambda_node)
                super().output(get_printable(arg_value))
        
            user_input = super().get_input()
            return create_value(user_input)
        
        # Return Value node from User-defined function
        elif source_node.elem_type == 'fcall':
            return_value = self.do_func_call(source_node)
            return return_value
        
        # Return Value node from Function method call
        elif source_node.elem_type == 'mcall':
            return_value = self.do_func_call(source_node)
            return return_value

        # Return Value node from Lambda function
        elif source_node.elem_type == 'lambda':
            # Get list of formal parameter variable names (i.e. lambda parameters)
            formal_param_name_list = []
            for arg in source_node.dict['args']:
                formal_param_name_list.append(arg.get('name'))

            # Capture all variables that aren't formal parameters
            captured_vars = {}
            for i in range(len(self.variable_scope_list)-1, -1, -1):
                curr_scope_dict = self.variable_scope_list[i]
                for key, value in curr_scope_dict.items():
                    if key not in formal_param_name_list:
                        if value.type() != Type.OBJ and value.type() != Type.LAMBDA:
                            captured_vars[key] = copy.deepcopy(value)
                 
            final_lambda_struct = [source_node, captured_vars]
            return Value(Type.LAMBDA, final_lambda_struct) # Value(Type.LAMBDA, [lambda_node, {var_names : curr_var_values}])

        super().error(
                ErrorType.NAME_ERROR,
                f"Expression is invalid",
            )
         
    # Inspired by https://stackoverflow.com/questions/4664850/how-to-find-all-occurrences-of-a-substring
    def find_var_indices(self, statement_node_str, substr):
        start = 0
        while True:
            start = statement_node_str.find(substr, start)
            if start == -1: return
            yield start
            start += len(substr) # Use start += 1 to find overlapping matches

    # Returns scope index if the variable name exists, and throws an error otherwise
    # However, when called with gentle = True, it does not throw an error when the variable is not defined
    def validate_var_name(self, var_name, gentle=False):
        # Iterate through scopes to see if variable name exists
        for i in range(len(self.variable_scope_list)-1, -1, -1):
            curr_scope_dict = self.variable_scope_list[i]
            if var_name in curr_scope_dict:
                return i
            
        if not gentle:
            super().error(
                ErrorType.NAME_ERROR,
                f"Variable {var_name} has not been defined",
            )
        return None
        
    # Run function calls (print, custom functions, lambdas, object method calls, etc.)
    def do_func_call(self, statement_node, outer_lambda_node = None):
        # Run print function
        if statement_node.dict['name'] == 'print':
            final_output = ""
            for arg in statement_node.dict['args']:
                arg_value = self.evaluate_expression(arg, outer_lambda_node)
                final_output += get_printable(arg_value)
            super().output(final_output)
            return Interpreter.NIL_VALUE
        
        # Run function call for a custom function
        function_elem = None
        functions_list = self.ast.dict['functions']
        if functions_list:
            for elem in functions_list:
                # Function matches if the function name and number of arguments is the same
                if elem.dict['name'] == statement_node.dict['name'] and len(elem.dict['args']) == len(statement_node.dict['args']):
                    function_elem = elem

        lambda_node = None # INNER lambda node
        object =  None

        # Run function call for a method call on an object
        if statement_node.elem_type == "mcall":
            obj_name = statement_node.dict['objref']
            method_name = statement_node.dict['name']
            scope_index = self.validate_var_name(obj_name)

            if scope_index is not None:
                var_value = None
                object = self.variable_scope_list[scope_index][obj_name]
                if object.type() != Type.OBJ:
                    super().error(
                        ErrorType.TYPE_ERROR,
                        "Trying to call method on non-object",
                    )

                obj_fields_dict = self.variable_scope_list[scope_index][obj_name].v
                # See if the method belongs to the object directly
                if method_name in obj_fields_dict:
                    var_value = obj_fields_dict[method_name]
                else:
                    # If the method is not directly on object, see if it belongs to the object's prototype
                    # (accounting for chained prototypes)
                    failed_to_find_method = False
                    while (True):
                        if 'proto' in obj_fields_dict:
                            obj = obj_fields_dict['proto']
                            if (obj.type() != Type.OBJ):
                                failed_to_find_method = True
                                break
                            obj_fields_dict = obj.v
                            if method_name in obj_fields_dict:
                                var_value = obj_fields_dict[method_name]
                                break
                        else:
                            failed_to_find_method = True
                            break

                    if failed_to_find_method:
                        # Attempting to get method that does not exist on this object
                        super().error(
                            ErrorType.NAME_ERROR,
                            "Method does not exist on this object",
                        )

                # Pre-processing for method call that is a custom function
                if var_value.t == Type.FUNC:
                    updated_statement_node = var_value.v
                    # Get the actual Function element 
                    if functions_list:
                        for elem in functions_list:
                            if elem.dict['name'] == updated_statement_node.dict['name']:
                                if len(elem.dict['args']) != len(statement_node.dict['args']):
                                    super().error(
                                        ErrorType.TYPE_ERROR,
                                        "Invalid number of args passed into function",
                                    )
                                else:
                                    function_elem = elem

                # Pre-processing for method call that is a lambda
                elif var_value.t == Type.LAMBDA:
                    function_elem = var_value.v[Interpreter.LAMBDA_NODE]
                    lambda_node = var_value.v

                    if object is not None and len(function_elem.dict['args']) != len(statement_node.dict['args']):
                        super().error(
                            ErrorType.NAME_ERROR,
                            "Invalid number of args passed into obj lambda method",
                        )

                    if len(function_elem.dict['args']) != len(statement_node.dict['args']):
                        super().error(
                            ErrorType.TYPE_ERROR,
                            "Invalid number of args passed into lambda",
                        )
                else:
                    super().error(
                        ErrorType.TYPE_ERROR,
                        "Attempting to call function on non-function variable type",
                    )

        # Process function within a variable
        if function_elem is None:
            scope_index = self.validate_var_name(statement_node.dict['name'])
            if scope_index is not None:
                var_value = self.variable_scope_list[scope_index][statement_node.dict['name']]
                # Variable references custom function
                if var_value.t == Type.FUNC:
                    updated_statement_node = var_value.v
                    # Get new function element
                    if functions_list:
                        for elem in functions_list:
                            if elem.dict['name'] == updated_statement_node.dict['name']:
                                if len(elem.dict['args']) != len(statement_node.dict['args']):
                                    super().error(
                                        ErrorType.TYPE_ERROR,
                                        "Invalid number of args passed into function",
                                    )
                                else:
                                    function_elem = elem

                # Variable references nested lambda

                # Captured variables take precedence over pass by reference inside of a lambda
                # Example -
                    # If inside a lambda, we update x which references y,
                    # and y is a captured variable, then we update the y variable outside of the lambda still
                    # BUT we reference the original y captured variable when inside the lambda
                                    
                # So, if we have a lambda node within another lambda node
                # We need to see if the variable that holds the inner lambda function is within the outer lambda node's captured variables
                # In this case, we need to reference the captured value of the variable instead of the actual value
                elif outer_lambda_node is not None and var_value.t == Type.LAMBDA and statement_node.dict['name'] in outer_lambda_node[Interpreter.CAPTURED_VARS]:
                    captured_vars_dict = outer_lambda_node[Interpreter.CAPTURED_VARS]
                    lambda_var_name = statement_node.dict['name']
                    lambda_node = captured_vars_dict[lambda_var_name]
                    function_elem = lambda_node.v[Interpreter.LAMBDA_NODE]
                
                # Variable references non-nested lambda
                elif var_value.t == Type.LAMBDA:
                    function_elem = var_value.v[Interpreter.LAMBDA_NODE]
                    lambda_node = var_value.v

                    if len(function_elem.dict['args']) != len(statement_node.dict['args']):
                        super().error(
                            ErrorType.TYPE_ERROR,
                            "Invalid number of args passed into lambda",
                        )
                else:
                    super().error(
                        ErrorType.TYPE_ERROR,
                        "Attempting to call function on non-function variable type",
                    )

        # Run function
        if function_elem is not None:
            # Set up scope for the function
            self.variable_scope_list.append({}) 
            self.variable_alias_list.append({})
            scope_index = len(self.variable_scope_list) - 1

            args_val_list = statement_node.dict['args']
            args_name_list = function_elem.dict['args']

            for i in range(len(args_val_list)):
                arg_val = self.evaluate_expression(args_val_list[i])
                arg_name = args_name_list[i].get('name')
               
                # Deep copy lambdas that aren't passed by reference
                if arg_val.t == Type.LAMBDA and args_name_list[i].elem_type != 'refarg':
                    self.variable_scope_list[scope_index][arg_name] = copy.deepcopy(arg_val)
                # Deep copy objects that aren't passed by reference
                elif arg_val.t == Type.OBJ and args_name_list[i].elem_type != 'refarg':
                    self.variable_scope_list[scope_index][arg_name] = copy.deepcopy(arg_val)
                # Assign normal arguments
                else:
                    self.variable_scope_list[scope_index][arg_name] = arg_val
                    
                # Set up variables that are passed by reference
                if args_name_list[i].elem_type == 'refarg':
                    ref_name = args_val_list[i].get('name')
                    self.variable_alias_list[scope_index][arg_name] = ref_name

            # If an object is calling the function, add the 'this' variable to the objref
            if object is not None:
                self.variable_scope_list[scope_index]["this"] = object
                self.variable_alias_list[scope_index]["this"] = statement_node.dict['objref'] # obj name

            return self.run_func(function_elem, lambda_node)
        else:
            super().error(
                    ErrorType.NAME_ERROR,
                    f"Function {statement_node.dict['name']} has not been defined",
                )
        
    def get_debug_info(self, ast):
        pass

def main():
    interpreter = Interpreter(trace_output=True)
    
    program = """
    func foo(ref x) {
    if (x.a > 9) {
    x.a = x.a - 1;
    print(x.a);
    foo(x);
    } else {
    print("reached the end!!!");
    }
    }

    func main() {
    x = @;
    x.a = 12;
    foo(x);
    print(x.a);
    }
    """

    interpreter.run(program)

if __name__ == "__main__":
    main()   