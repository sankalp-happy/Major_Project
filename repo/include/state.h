#ifndef STATE_H
#define STATE_H

extern double g_discount_percent;
extern double g_last_total;

void set_discount_percent(double value);
double get_discount_percent(void);

void set_last_total(double value);
double get_last_total(void);

#endif
