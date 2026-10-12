/* Minimal bionic executable entry, matching the firmware executable's CRT ABI. */
.text
.global _start
.type _start,%function
_start:
 mov x0, sp
 mov x1, xzr
 adrp x2, main
 add x2, x2, :lo12:main
 adrp x3, structors
 add x3, x3, :lo12:structors
 b __libc_init
.section .data.rel.ro
.balign 8
structors:
 .xword empty, empty, empty
empty:
 .xword -1, 0
