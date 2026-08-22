"""Pack-authored checkpoints were removed (feature 004 / T015).

Pause and resume use kernel `pause_checkpoint` written by
`KernelActionExecutor`. This module no longer constructs `MemoryRecord`s
or calls `memory.write`.
"""
