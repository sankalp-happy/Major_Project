#ifndef TYPES_H
#define TYPES_H

#include <stddef.h>

typedef struct {
    char name[32];
    double price;
    int qty;
} Item;

typedef struct {
    Item *items;
    size_t count;
} Cart;

#endif
