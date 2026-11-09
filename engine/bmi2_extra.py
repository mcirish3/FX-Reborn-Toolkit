"""Lowering for the BMI2 instructions FX Reborn never needed: RORX, MULX, PDEP, PEXT.

Same contract as bmi2_lower.lower(): returns a position-independent body that
leaves every register except the destination(s) and all flags unchanged (none
of these four instructions write flags), borrows stack below RSP, and accepts
external_stack_adjust=8 when the caller pushed a return address first.

Strategy: push result slot(s), RFLAGS and the scratch registers RAX, RCX, RDX,
R8, R9; read a memory operand first (before any scratch register changes, so
addressing registers are still original); read register operands from their
saved slots; compute with plain x86-64; store results into the slots; pop
everything back, destination last. Using ordinary instructions only.
"""
from __future__ import annotations

import iced_x86 as ix

from bmi2_lower import FULL, GPRS32, GPRS64, LOW32, LoweringError, _Builder, _signed64

R, C, I, M = ix.Register, ix.Code, ix.Instruction, ix.MemoryOperand

SUPPORTED = {
    C.VEX_RORX_R32_RM32_IMM8: ("RORX", 32), C.VEX_RORX_R64_RM64_IMM8: ("RORX", 64),
    C.VEX_MULX_R32_R32_RM32: ("MULX", 32), C.VEX_MULX_R64_R64_RM64: ("MULX", 64),
    C.VEX_PDEP_R32_R32_RM32: ("PDEP", 32), C.VEX_PDEP_R64_R64_RM64: ("PDEP", 64),
    C.VEX_PEXT_R32_R32_RM32: ("PEXT", 32), C.VEX_PEXT_R64_R64_RM64: ("PEXT", 64),
}
SCRATCH = [R.RAX, R.RCX, R.RDX, R.R8, R.R9]   # push order


def lower(ins: ix.Instruction, ip: int = 0, external_stack_adjust: int = 0) -> bytes:
    if ins.code not in SUPPORTED:
        raise LoweringError(f"Unsupported instruction: {ins}")
    if external_stack_adjust not in (0, 8):
        raise LoweringError("external_stack_adjust must be 0 or 8")
    op, bits = SUPPORTED[ins.code]
    regs = GPRS64 if bits == 64 else GPRS32
    dests = [ins.op0_register] + ([ins.op1_register] if op == "MULX" else [])
    for d in dests:
        if d not in regs or FULL[d] == R.RSP:
            raise LoweringError("Destination must be a GPR other than RSP")
    rm_index = 1 if op == "RORX" else 2
    for n in range(ins.op_count):
        if ins.op_kind(n) == ix.OpKind.REGISTER and ins.op_register(n) not in regs:
            raise LoweringError("Unexpected register width")

    b = _Builder()
    emit = b.emit
    # Result slots: for MULX the low-half destination (op1) is popped first and
    # the high half (op0) last, so op0==op1 ends with the high half, as on hardware.
    order = [FULL[ins.op0_register]] + ([FULL[ins.op1_register]] if op == "MULX" else [])
    for d in order:
        emit(I.create_reg(C.PUSH_R64, d))
    emit(I.create(C.PUSHFQ))
    for reg in SCRATCH:
        emit(I.create_reg(C.PUSH_R64, reg))
    frame = 8 * (len(order) + 1 + len(SCRATCH))
    slot = {reg: 8 * (len(SCRATCH) - 1 - i) for i, reg in enumerate(SCRATCH)}   # R9 at 0 ... RAX at 32
    result_slot = {order[i]: frame - 8 * (i + 1) for i in range(len(order))}
    mov = C.MOV_R64_RM64

    def read_reg(target64, source):
        s64 = FULL[source]
        if s64 in slot:
            emit(I.create_reg_mem(mov, target64, M(R.RSP, displ=slot[s64], displ_size=1)))
        elif s64 == R.RSP:
            emit(I.create_reg_mem(C.LEA_R64_M, target64, M(R.RSP, displ=frame + external_stack_adjust, displ_size=1)))
        else:
            emit(I.create_reg_reg(mov, target64, s64))
        if bits == 32:   # zero-extend: the 32-bit forms only see the low half
            emit(I.create_reg_reg(C.MOV_R32_RM32, LOW32[target64], LOW32[target64]))

    def read_operand(target64, n):
        if ins.op_kind(n) == ix.OpKind.REGISTER:
            read_reg(target64, ins.op_register(n))
            return
        if ins.is_ip_rel_memory_operand:
            emit(I.create_reg_u64(C.MOV_R64_IMM64, target64, ins.ip_rel_memory_address))
            mem = M(target64, seg=ins.segment_prefix)
        else:
            base, index = ins.memory_base, ins.memory_index
            disp = _signed64(ins.memory_displacement)
            if index in (R.RSP, R.ESP):
                raise LoweringError("RSP cannot be an x86 SIB index")
            if base in (R.RSP, R.ESP):
                if index == R.NONE and disp < 0 and disp + bits // 8 > -(frame + external_stack_adjust):
                    raise LoweringError("Memory source overlaps the borrowed stack frame")
                disp = _signed64(disp + frame + external_stack_adjust)
            address32 = base in GPRS32 or index in GPRS32
            displ_size = 1 if -128 <= disp <= 127 else (4 if address32 else 8)
            if base == R.NONE and index == R.NONE:
                displ_size = ins.memory_displ_size
            mem = M(base, index, ins.memory_index_scale, disp, displ_size, seg=ins.segment_prefix)
        if bits == 64:
            emit(I.create_reg_mem(mov, target64, mem))
        else:
            emit(I.create_reg_mem(C.MOV_R32_RM32, LOW32[target64], mem))

    # Memory first, while every addressing register still holds its original value.
    read_operand(R.R8, rm_index)
    if op == "RORX":
        emit(I.create_reg_reg(mov, R.RAX, R.R8))
        rot = C.ROR_RM64_IMM8 if bits == 64 else C.ROR_RM32_IMM8
        emit(I.create_reg_i32(rot, R.RAX if bits == 64 else R.EAX, ins.immediate8 & (bits - 1)))
        emit(I.create_mem_reg(C.MOV_RM64_R64, M(R.RSP, displ=result_slot[order[0]], displ_size=1), R.RAX))
    elif op == "MULX":
        read_reg(R.RAX, R.RDX)   # implicit source: original RDX/EDX
        if bits == 64:
            emit(I.create_reg(C.MUL_RM64, R.R8))
        else:
            emit(I.create_reg(C.MUL_RM32, R.R8D))   # EDX:EAX, both zero-extended
        emit(I.create_mem_reg(C.MOV_RM64_R64, M(R.RSP, displ=result_slot[order[0]], displ_size=1), R.RDX))
        emit(I.create_mem_reg(C.MOV_RM64_R64, M(R.RSP, displ=result_slot[order[1]], displ_size=1), R.RAX))
    else:
        # RAX = source bits (op1), RCX = mask (op2), RDX = result, R8 = running bit
        emit(I.create_reg_reg(mov, R.RCX, R.R8))
        read_operand(R.RAX, 1)
        emit(I.create_reg_reg(C.XOR_R32_RM32, R.EDX, R.EDX))
        emit(I.create_reg_i32(C.MOV_R32_IMM32, R.R8D, 1))
        b.label("loop")
        emit(I.create_reg_reg(C.TEST_RM64_R64, R.RCX, R.RCX))
        b.branch(C.JE_REL8_64, "done")
        emit(I.create_reg_reg(mov, R.R9, R.RCX))
        emit(I.create_reg(C.NEG_RM64, R.R9))
        emit(I.create_reg_reg(C.AND_R64_RM64, R.R9, R.RCX))            # lowest set mask bit
        if op == "PDEP":
            emit(I.create_reg_reg(C.TEST_RM64_R64, R.RAX, R.R8))        # next source bit set?
            b.branch(C.JE_REL8_64, "skip")
            emit(I.create_reg_reg(C.OR_R64_RM64, R.RDX, R.R9))
        else:
            emit(I.create_reg_reg(C.TEST_RM64_R64, R.RAX, R.R9))        # source bit under mask set?
            b.branch(C.JE_REL8_64, "skip")
            emit(I.create_reg_reg(C.OR_R64_RM64, R.RDX, R.R8))
        b.label("skip")
        emit(I.create_reg_reg(C.ADD_R64_RM64, R.R8, R.R8))
        emit(I.create_reg_mem(C.LEA_R64_M, R.R9, M(R.RCX, displ=-1, displ_size=1)))
        emit(I.create_reg_reg(C.AND_R64_RM64, R.RCX, R.R9))            # clear lowest mask bit
        b.branch(C.JMP_REL8_64, "loop")
        b.label("done")
        emit(I.create_mem_reg(C.MOV_RM64_R64, M(R.RSP, displ=result_slot[order[0]], displ_size=1), R.RDX))

    for reg in reversed(SCRATCH):
        emit(I.create_reg(C.POP_R64, reg))
    emit(I.create(C.POPFQ))
    for d in reversed(order):
        emit(I.create_reg(C.POP_R64, d))
    return b.encode(ip)
