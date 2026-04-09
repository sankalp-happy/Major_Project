#ifndef CART_H
#define CART_H

#include "types.h"

double calculate_subtotal(const Cart *cart);
double checkout_total(const Cart *cart);

#endif
