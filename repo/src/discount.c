#include "discount.h"
#include "state.h"

double apply_global_discount(double amount) {
    double pct = get_discount_percent();
    double reduced = amount - (amount * pct / 100.0);
    if (reduced < 0.0) {
        return 0.0;
    }
    return reduced;
}
