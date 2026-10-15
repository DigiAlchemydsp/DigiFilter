/* The OB-1 kernel's cost on the ColdFire: tests/ob1_bench.py links this with ob1_vcf.c at 0x10000 and counts
 * the instructions of ob1_bench(), one 32-sample block of voice 0 on ob1_io, in Unicorn. */
#include "ob1_vcf.h"

int ob1_io[32];

void ob1_bench(int tap, int fi8, int qi)
{
    ob1_vcf_run(tap, fi8, qi, ob1_io, 0);
}
