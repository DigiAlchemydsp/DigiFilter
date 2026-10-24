/* Host/Unicorn harness for the Filter+FX DSP wrapper. */
extern void fx_run(int mode, int fi, int qi, int aux1, int aux2, int *buf, int voice);

int fx_mode, fx_fi, fx_qi, fx_a1, fx_a2;
int fx_buf[64];

void fx_run_test(void)
{
    fx_run(fx_mode, fx_fi, fx_qi, fx_a1, fx_a2, fx_buf, 0);
}
