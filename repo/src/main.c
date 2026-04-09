#include <stdio.h>

#include "cart.h"
#include "state.h"
#include "types.h"

int main(void) {
    Item items[] = {
        {"Notebook", 50.0, 2},
        {"Pen", 10.0, 3},
        {"Bag", 120.0, 1}
    };
    Cart cart;
    double total;

    cart.items = items;
    cart.count = sizeof(items) / sizeof(items[0]);

    set_discount_percent(10.0);
    total = checkout_total(&cart);

    printf("Items: %zu\n", cart.count);
    printf("Discount: %.2f%%\n", get_discount_percent());
    printf("Final total: %.2f\n", total);
    printf("Stored global last total: %.2f\n", get_last_total());

    return 0;
}
