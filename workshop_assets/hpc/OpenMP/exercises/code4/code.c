/* SPDX-License-Identifier: Apache-2.0
 * OpenMP debugging exercise: unsynchronised shared counter.
 */
#include <stdio.h>
#include <omp.h>

int main(void)
{
    const int iterations = 100000;
    int counter = 0;

    #pragma omp parallel for
    for (int i = 0; i < iterations; ++i) {
        counter += 1;
    }

    printf("Counter: %d; expected: %d\n", counter, iterations);
    printf("Observed comparison: %s\n",
           counter == iterations ? "MATCH" : "MISMATCH");

    /* Permit repeated observations; exit 0 is not a correctness proof. */
    return 0;
}
