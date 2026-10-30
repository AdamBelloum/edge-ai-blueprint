/* SPDX-License-Identifier: Apache-2.0
 * OpenMP debugging exercise: incomplete loop coverage.
 */
#include <stdio.h>
#include <omp.h>

int main(void)
{
    enum { N = 8 };
    int values[N];
    int correct = 1;

    for (int i = 0; i < N; ++i) {
        values[i] = -1;
    }

    #pragma omp parallel for
    for (int i = 0; i < N - 1; ++i) {
        values[i] = i * i;
    }

    for (int i = 0; i < N; ++i) {
        printf("values[%d] = %d; expected %d\n",
               i, values[i], i * i);
        if (values[i] != i * i) {
            correct = 0;
        }
    }

    printf("Coverage check: %s\n", correct ? "PASS" : "FAIL");
    return correct ? 0 : 1;
}
