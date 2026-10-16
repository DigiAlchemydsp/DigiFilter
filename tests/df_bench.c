/* Instruction-count bench driver for the digifilter per-voice DSP path.
 * Built by tests/df_bench.py with the SDK's own flags; calls digifilter_filt()
 * for one 32-frame block of voice 0 with the globals below set by the harness. */
typedef int int32;
extern int digifilter_filt(unsigned char *params, int *buf, int active, int voice);
unsigned char df_params[0x100];
int df_buf[64];
int df_filt_run(void) { return digifilter_filt(df_params, df_buf, 1, 0); }
