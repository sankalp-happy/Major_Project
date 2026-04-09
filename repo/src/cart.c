#include "cart.h"
#include "discount.h"
#include "state.h"

double calculate_subtotal(const Cart *cart) {
    size_t i;
    double subtotal = 0.0;

    if (cart == 0 || cart->items == 0) {
        return 0.0;
    }

    for (i = 0; i < cart->count; ++i) {
        subtotal += cart->items[i].price * (double)cart->items[i].qty;
    }

    return subtotal;
}

double checkout_total(const Cart *cart) {
    double subtotal = calculate_subtotal(cart);
    double total = apply_global_discount(subtotal);
    set_last_total(total);
    return total;
}
