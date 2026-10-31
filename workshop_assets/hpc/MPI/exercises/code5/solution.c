/******************************************************************************
* FILE: mpi_bug5.c
* DESCRIPTION:
*   This is an "unsafe" program. It's behavior varies depending upon the
*   platform and MPI library
* AUTHOR: Blaise Barney
* LAST REVISED: 01/24/09
******************************************************************************/
#include "mpi.h"
#include <stdio.h>
#include <stdlib.h>

#define MSGSIZE 2000

int main (int argc, char *argv[])
{
int        numtasks, rank, i, tag=111, dest=1, source=0, count=0;
char       data[MSGSIZE];
double     start, end, result;
MPI_Status status;

MPI_Init(&argc,&argv);
MPI_Comm_size(MPI_COMM_WORLD, &numtasks);
MPI_Comm_rank(MPI_COMM_WORLD, &rank);

if (rank == 0) {
  printf ("mpi_bug5 has started...\n");
  if (numtasks > 2)
    printf("INFO: Number of tasks= %d. Only using 2 tasks.\n", numtasks);
  }

/******************************* Send task **********************************/
if (rank == 0) {

  /* Initialize send data */
  for(i=0; i<MSGSIZE; i++)
     data[i] =  'x';

  start = MPI_Wtime();
  for (int message = 0; message < 20; message++) {
    MPI_Send(data, MSGSIZE, MPI_BYTE, dest, tag, MPI_COMM_WORLD);
    count++;
    if (count % 10 == 0) {
      end = MPI_Wtime();
      printf("Count= %d  Time= %f sec.\n", count, end-start);
      start = MPI_Wtime();
      }
    }
  }

/****************************** Receive task ********************************/

if (rank == 1) {
  for (int message = 0; message < 20; message++) {
    MPI_Recv(data, MSGSIZE, MPI_BYTE, source, tag, MPI_COMM_WORLD, &status);
    /* Do some work  - at least more than the send task */
    result = 0.0;
    for (i=0; i < 10000; i++)
      result = result + (double)random();
    count++;
    }
  }

if (rank < 2)
  printf("Task %d completed %d messages\n", rank, count);

MPI_Finalize();
}
