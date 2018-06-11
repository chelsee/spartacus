#!/usr/bin/env python
#  -*- coding: <utf-8> -*-
"""
This file is part of Spartacus project
Copyright (C) 2018  CSE

This program is free software; you can redistribute it and/or modify
it under the terms of the GNU General Public License as published by
the Free Software Foundation; either version 2 of the License, or
(at your option) any later version.

This program is distributed in the hope that it will be useful,
but WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
GNU General Public License for more details.

You should have received a copy of the GNU General Public License along
with this program; if not, write to the Free Software Foundation, Inc.,
51 Franklin Street, Fifth Floor, Boston, MA 02110-1301 USA.
"""

__author__ = "CSE"
__copyright__ = "Copyright 2018, CSE"
__credits__ = ["CSE"]
__license__ = "GPL"
__version__ = "2.1"
__maintainer__ = "CSE"
__status__ = "Dev"

from ToolChain.Assembler.Constants import REGISTERS, \
                                          INSTRUCTION_LIST, \
                                          LABEL_INSTRUCTIONS, \
                                          STATE_LIST, \
                                          MEMORY_REFERENCE_INDICATORS, \
                                          EXPORTED_REFERENCE_INDICATOR, \
                                          DATA_NUMERIC_INDICATOR, \
                                          DATA_ALPHA_INDICATOR, \
                                          DATA_MEMORY_REFERENCE, \
                                          COMMENT_INDICATORS

from CapuaEnvironment.IntructionFetchUnit.FormDescription import formDescription
from CapuaEnvironment.Instruction.OperationDescription import operationDescription

import struct
import re


class Parser:
    """
    This class is used to parse the text format code and build a list of instruction from it.
    To do so, it has a direct link into CapuaEnvironment instruction information. Those class
    and description files are directly used in order to help build the binary code required
    to run code inside of the Capua environment. The steps are as follows:
    1. Verify if the file name is valid, and that it is not empty.
    2. Read the file and parse each line into a list to be evaluated one at a time.
    3. Evaluate each line and, if not an empty line, store instructions and memory references in lists.
        - Parse each line and determine whether we're dealing with an instruction, memory reference, data, etc.
        - If an instruction is found, determine all possible forms for this instruction (eg. ins - reg - reg)
        - Using possible forms for an instruction, determine the correct instruction code based on given arguments.
    4. Once all info has been evaluated, if correct, we generate the binary code for each instruction
    """

    relativeAddressCounter = 0                # Used to determine memory address of a label at a given point in the file
    lineno = 0                                # Used to pinpoint where ValueErrors are raised

    def parse(self, text):
        """
        This is the main driver method for the parser. It takes in an individual line of code, parses the info and
        sends the fully built binary code to the assembler, or returns a memory reference with the appropriate offset.
        :param text: Str, The line of text as read from the file
        :return: The encoded binary instruction for the line, the current offset, and the label flag used by assembler
        """

        line = text.split()                     # We split the line with space as a delimiter. Each token is an argument
        instruction = b""                       # Instruction will be written as a bytestring
        arglist = []                            # We keep each argument in a list to evaluate later
        found = False                           # Flag to indicate if instruction was found in state list
        form = "Ins"                            # We assume the first argument is an instruction
        labelFlag = 0                           # Used by the assembler to determine what we're returning
        dataIdentifier = line[0].upper()        # used for special identifiers such as .dataAlpha, comments etc.
        self.lineno += 1

        # First off, we need to determine if this line has a label or global label to be referenced
        # If so, we can simply return to the Assembler class with the label, the offset, and the appropriate flag
        identifierMatch = re.search(r'(\.(\w*))|(\w*:)|(;)', dataIdentifier)

        if identifierMatch:
            # We had a match for identifier patterns, so we assume there's no instruction.
            instruction, labelFlag = self._evaluateIndicatorData(text, dataIdentifier, line, instruction, labelFlag)
            return instruction, self.relativeAddressCounter, labelFlag

        elif line[0].upper() in INSTRUCTION_LIST:
            # Next we check if the first item on the line is an instruction
            # If we make it to this line, there were no data indicators (.dataAlpha, comments, labels etc.)
            line = text.upper()
            line = line.split()
            labelFlag = 0

            # We build our instruction's form by verifying each argument after the instruction
            # This will allow us to determine which "state" the instruction belongs to.
            form, arglist = self._evaluateFormBasedOnArguments(line, form, arglist)
            instruction += self._findInstructionCode(form, line, instruction)
            state = self._definestate(form)

            # Finally we evaluate how we will build our binary code. Each state has a distinct pattern we must follow
            instruction = self._buildBinaryCode(line[0], state, arglist, instruction)

        else:
            # The instruction was not in the list, and no identifier mnemonics were found.
            raise ValueError("Invalid code format at line " + str(self.lineno))

        return instruction, self.relativeAddressCounter, labelFlag

    def _findInstructionCode(self, form, line, instruction):
        """
        Finds the instruction's binary code based on its form, which relies on the arguments after the instruction.
        Since each instruction + form pair has one distinct instruction length, we also add it here to the
        relativeAddressCounter.
        :param form: str, the assembled form of the particular instruction (ex: instruction-register-register)
        :param line: str list, our line read from input split into individual arguments
        :param instruction: bytestring, will contain our final binary code passed back to assembler
        :return: our instruction's correct binary code
        """

        try:
            # We make sure the form is described in the formDescription Class
            insform = formDescription[form]
            ins = operationDescription[line[0]]

        except KeyError as e:
            raise ValueError("Invalid instruction format at line " + str(self.lineno))

        found = False

        for possiblecodes in ins:
            # We shift the binary code by 4 bits to see if we have a match with typeCode for this form
            # ex: typeCode = 0010, possiblecodes = 00101011 would be true since the first 4 bits match.
            # Once we have our instruction match, we know the size of the instruction and we add to the counter
            if insform["typeCode"] is (possiblecodes >> 4):
                found = True
                self.relativeAddressCounter += insform["length"]
                instruction += bytes((possiblecodes,))

        if not found:
            # We shouldn't get to this part since the instruction was in the instruction list. Code error.
            raise ValueError("Invalid instruction format at line " + str(self.lineno))


        return instruction

    def _definestate(self, form):
        """
        Takes in the form based on instruction and its arguments and determines which form it belongs to.
        This state contains all possible instructions for that particular form.
        :param form: str, The form of the instruction based on its arguments (ex: instruction-register-immediate)
        :return: The appropriate state string for the instruction form
        """

        try:
            state = STATE_LIST[form]

        except KeyError as e:
            # Form is invalid, doesn't fit any state descriptions
            raise ValueError("Invalid instruction format at line " + str(self.lineno))

        return state

    def _evaluateIndicatorData(self, text, dataIdentifier, line, instruction, labelFlag):
        """
        This method indicates that we are NOT dealing with an instruction, and that we must parse data for a string,
        numeric value, a comment, a label, or global reference.
        :param text: str, The raw line of text as read from the file directly
        :param dataIdentifier: str, The first argument of the line, used to determine which identifier we have
        :param line: str list, The line split into individual arguments using a space delimiter by default
        :param instruction: bytestring, Will contain the piece of data based on the appropriate identifier
        :param labelFlag: int, Used by Assembler to determine if we return a label, global ref, or data/instruction
        :return: Instruction containing relevant data, and the appropriate flag to be used by the assembler
        """
        if dataIdentifier[-1] == MEMORY_REFERENCE_INDICATORS and dataIdentifier[0] != COMMENT_INDICATORS:
            # We wouldn't want to accidentally add a memory reference that was part of a comment

            if dataIdentifier.count(MEMORY_REFERENCE_INDICATORS) > 1:
                # Forcing coding standard: labels can't contain colons ":"
                raise ValueError("Syntax error, memory reference has too many \":\"")
            instruction = dataIdentifier[:-1].upper()
            labelFlag = 1

        elif dataIdentifier == EXPORTED_REFERENCE_INDICATOR:
            # Global (external) label that can be used by other files
            instruction = line[1].upper()
            labelFlag = 2

        elif dataIdentifier[0] == COMMENT_INDICATORS:
            # Just a comment, we simply ignore
            instruction = ""
            labelFlag = 3

        elif dataIdentifier == DATA_ALPHA_INDICATOR:
            # DataAlpha text, which must be converted into bytestring
            text = text.split(maxsplit=1)
            instruction += text[1][:-1].encode("utf-8")
            self.relativeAddressCounter += len(instruction) + 1
            instruction += b'\x00'

        elif dataIdentifier == DATA_NUMERIC_INDICATOR:
            # DataNumeric number which must be converted to binary
            numeric = self.translateTextImmediate(line[1][1:])
            instruction += struct.pack(">I", numeric)
            self.relativeAddressCounter += 4

        elif dataIdentifier == DATA_MEMORY_REFERENCE:
            # Memory reference, label will be returned as the instruction
            if line[1][0] == MEMORY_REFERENCE_INDICATORS:
                memref = line[1][1:].upper()
            else:
                memref = line[1].upper()
            instruction += b':' + memref.encode("utf-8") + b':'
            self.relativeAddressCounter += 4

        else:
            # Identifier not in accepted list
            raise ValueError("Invalid instruction format at line " + str(self.lineno) + " \n" + dataIdentifier)

        return instruction, labelFlag

    def _evaluateFormBasedOnArguments(self, line, form, arglist):
        """
        Method looks at the whole line after the initial instruction and determines its form based on the arguments.
        Registers are concatenated as "REG", immediates and lables as "IMM", etc. We also populate a list of arguments
        as they are to be constructed into binary code later.
        :param line: str list, Line split into individual arguments
        :param form: str, will be built up based on arguments on the line in this method
        :param arglist: str list, Will contain our list of arguments to be used later when assembling our binary code
        :return: Fully constructed form and newly populated list of arguments
        """

        argcount = 0

        for arg in line[1:]:
            if arg[0] == "$":
                form += "Reg"
            elif arg[0] == "#":
                form += "Imm"
            elif arg[0] == "<" and arg[-1] == ">":
                form += "Flag"
            elif arg[0] == "[" and arg[-1] == "]":
                form += "Width"
            elif arg[0] == ";":
                # We found a comment, we break out of the loop
                break
            else:
                form += "Imm"
            arglist.append(arg)                      # We store the arguments to use later when building our binary code
            argcount += 1

        if argcount > 3:
            raise ValueError("Invalid instruction format: Too many arguments at line " + str(self.lineno))

        return form, arglist

    def _buildBinaryCode(self, ins, state, arglist, instruction):
        """
        This is the last step in parsing a line of code: assembling the actual binary code. Each state has a particular
        structure that is needed to be read correctly by the Capua VM. This method takes care of every form and gets
        the binary values for each register and immediate value. Labels are converted to bytestring as they are.
        :param ins: str, the actual instruction itself
        :param state: str, State of the instruction based on evaluated form (ex: instruction-register = STATE1)
        :param arglist: str list, List of arguments to be converted to binary code and assembled
        :param instruction: bytestring, our final binary code to be returned to the assembler
        :return: The newly built binary code for the instruction and arguments
        """

        if state == "STATE0":
            # Instruction is already complete, there is only one argument (the instruction itself, Ins)
            pass

        elif state == "STATE1":
            # Form = Instruction - Register
            register = self.translateRegisterName(arglist[0][1:])
            instruction += bytes(0b0000) + bytes((register,))

        elif state == "STATE2":
            # Form = Instruction - Register - Register
            register = self.translateRegisterName(arglist[0][1:])
            register2 = self.translateRegisterName(arglist[1][1:])
            register = (register << 4) + register2
            instruction += bytes((register,))

        elif state == "STATE3":
            # Form = Instruction - Immediate
            if arglist[0][0] == "#":
                immediate = self.translateTextImmediate(arglist[0][1:])
                instruction += immediate.to_bytes(4, byteorder='big')
            elif ins in LABEL_INSTRUCTIONS:
                instruction += b':' + arglist[0].encode("utf-8") + b':'

        elif state == "STATE4":
            # Form = Instruction - Immediate - Register
            register = self.translateRegisterName(arglist[1][1:])
            if arglist[0][0] == "#":
                immediate = self.translateTextImmediate(arglist[0][1:])
                instruction += immediate.to_bytes(4, byteorder='big') + bytes(0b0000) + bytes((register,))
            elif ins in LABEL_INSTRUCTIONS:
                instruction += b':' + arglist[0].encode("utf-8") + b':' + bytes(0b0000) + bytes((register,))

        elif state == "STATE5":
            # Form = Instruction - Width - Immediate - Immediate
            width = arglist[0][1:-1]
            immediate = self.translateTextImmediate(arglist[1][1:])
            immediate2 = self.translateTextImmediate(arglist[2][1:])
            width = self.translateTextImmediate(width)
            instruction += bytes(0b0000) + bytes((width,)) + immediate.to_bytes(4, byteorder='big') + \
                                                             immediate2.to_bytes(4, byteorder='big')

        elif state == "STATE6":
            # Form = Instruction - Width - Immediate - Register
            width = arglist[0][1:-1]
            immediate = self.translateTextImmediate(arglist[1][1:])
            register = self.translateRegisterName(arglist[2][1:])
            width = self.translateTextImmediate(width)
            width = (width << 4) + register
            instruction += bytes((width,)) + immediate.to_bytes(4, byteorder='big')

        elif state == "STATE7":
            # Form = Instruction - Width - Register - Immediate
            width = arglist[0][1:-1]
            register = self.translateRegisterName(arglist[1][1:])
            immediate = self.translateTextImmediate(arglist[2][1:])
            width = self.translateTextImmediate(width)
            width = (width << 4) + register
            instruction += bytes((width,)) + immediate.to_bytes(4, byteorder='big')

        elif state == "STATE8":
            # Form = Instruction - Width - Register - Register
            width = arglist[0][1:-1]
            register = self.translateRegisterName(arglist[1][1:])
            register2 = self.translateRegisterName(arglist[2][1:])
            width = self.translateTextImmediate(width)
            width = (width << 4) + register
            instruction += bytes((width,)) + bytes((register2,))

        elif state == "STATE9":
            # Form = Instruction - Flag - Immediate
            flag = self.translateTextFlags(arglist[0][1:-1])
            if arglist[1][0] == "#":
                immediate = self.translateTextImmediate(arglist[1][1:])
                instruction += bytes((flag,)) + bytes(0b0000) + immediate.to_bytes(4, byteorder='big')
            elif ins in LABEL_INSTRUCTIONS:
                instruction += bytes((flag,)) + bytes(0b0000) + b':' + arglist[1].encode("utf-8") + b':'

        elif state == "STATE10":
            # Form = Instruction - Flag - Register
            flag = self.translateTextFlags(arglist[0][1:-1])
            register = self.translateRegisterName(arglist[1][1:])
            flag = (flag << 4) + register
            instruction += bytes((flag,))

        else:
            # Nothing was valid in the first argument
            raise ValueError("Invalid instruction format at line " + str(self.lineno))

        return instruction

    def translateRegisterName(self, registerName: str=""):
        """
        This takes a register name and returns a register code as per:
            A = 0b0000
            B = 0b0001
            C = 0b0010
            etc...
        Throws error if register is not valid
        :param registerName: str, representing the register that needs translation
        :return: int, the int that represents the register
        """

        try:
            registerCode = REGISTERS[registerName.upper()]

        except KeyError as e:
            raise ValueError("Invalid instruction format: Too many arguments at line " + str(self.lineno))

        return registerCode

    def translateTextImmediate(self, textImmediate: str = ""):
        """
        This will translate an immediate value in a way that can be understood by the architecture.
        :param textImmediate: str, an immediate value to be translated
        :return: int, an immediate that can be worked on
        """

        immediate = None
        isNegative = False
        textImmediate = textImmediate.lower()  # Needed in case of 0XFF instead of 0xFF

        if textImmediate[0] == "-":
            isNegative = True
            textImmediate = textImmediate[1:]

        if len(textImmediate) > 2 and textImmediate[0:2] == "0b":
            # Indicates binary immediate
            baseToUse = 2
            textImmediate = textImmediate[2:]
        elif len(textImmediate) > 2 and textImmediate[0:2] == "0x":
            # Indicate hexadecimal immediate
            baseToUse = 16
            textImmediate = textImmediate[2:]
        else:
            # Take a leap of faith! This should be base 10
            baseToUse = 10

        immediate = int(textImmediate, baseToUse)

        validationImmediate = immediate
        immediate &= 0xFFFFFFFF  # Maximum immediate value is 32 bits

        if validationImmediate != immediate:
            raise ValueError("Given immediate value is too big, {} received but maxim value is 0xFFFFFFFF".format(
                hex(validationImmediate)))

        if isNegative:
            # If number was negative, get the 2 complement for this number
            immediate ^= 0xFFFFFFFF  # Flips all the bits, yield the 1 complement
            immediate += 1  # 1 complement + 1 gives the 2 complement
            immediate &= 0xFFFFFFFF  # Trim down to acceptable size!

        return immediate

    def translateTextFlags(self, textFlags):
        """
        Will translate a text FLAGs to flags code as:
        FLAGS: 0b000 : Zero, Lower, Higher
        :param textFlags: str, the flags themselves as a string
        :return:
        """
        codeFlags = 0b000
        originalFlags = textFlags
        textFlags = textFlags.lower()

        if "z" in textFlags or "e" in textFlags:
            codeFlags |= 0b100
            textFlags = textFlags.replace("z", "")
            textFlags = textFlags.replace("e", "")

        if "l" in textFlags:
            codeFlags |= 0b010
            textFlags = textFlags.replace("l", "")

        if "h" in textFlags:
            codeFlags |= 0b001
            textFlags = textFlags.replace("h", "")

        if len(textFlags) > 0:
            # Invalid flag selection detected!
            raise ValueError("Invalid conditional flag detected {} was provided but is invalid".format(originalFlags))

        return codeFlags
