/* SPDX-License-Identifier: Apache-2.0
 * Reference solution: create an OpenMP parallel region.
 */
#include <stdio.h>
#include <omp.h>

int main(void)
{
    #pragma omp parallel
    {
        printf("Hello from thread %d of %d\n",
               omp_get_thread_num(), omp_get_num_threads());
    }

    return 0;
}
