/* SPDX-License-Identifier: Apache-2.0
 * OpenMP debugging exercise: shared sum without reduction.
 */
#include <stdio.h>
#include <omp.h>

int main(void)
{
    const int n = 10000;
    long long sum = 0;
    const long long expected = (long long)n * (n + 1) / 2;

    #pragma omp parallel for
    for (int i = 1; i <= n; ++i) {
        sum += i;
    }

    printf("Sum: %lld; expected: %lld\n", sum, expected);
    printf("Observed comparison: %s\n",
           sum == expected ? "MATCH" : "MISMATCH");

    /* Permit repeated observations; exit 0 is not a correctness proof. */
    return 0;
}
