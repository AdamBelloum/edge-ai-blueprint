# code3 — Reference explanation

Add `reduction(+:sum)` to the parallel-for directive.

OpenMP supplies a private reduction copy for each participating
thread, initialised to the identity for addition: zero.
Threads update their own copies. OpenMP combines them using
addition when the construct finishes.

This removes concurrent unsynchronised updates to the shared sum.
The expected result is 50005000.

The result fits comfortably in `long long`; this example does
not rely on signed integer overflow. Integer addition here
also avoids floating-point rounding-order complications.

Running the buggy program with one thread may hide the race.
Running it repeatedly is useful for observation, but is not a
substitute for reasoning about shared memory.

Viewing this solution does not modify your working file.
