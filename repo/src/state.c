#include "state.h"

double g_discount_percent = 10.0;
double g_last_total = 0.0;

void set_discount_percent(double value) {
    if (value < 0.0) {
        g_discount_percent = 0.0;
        return;
    }
    if (value > 90.0) {
        g_discount_percent = 90.0;
        return;
    }
    g_discount_percent = value;
}

double get_discount_percent(void) {
    return g_discount_percent;
}

void set_last_total(double value) {
    g_last_total = value;
}

double get_last_total(void) {
    return g_last_total;
}
