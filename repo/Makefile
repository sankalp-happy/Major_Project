CC = gcc
CFLAGS = -std=c11 -Wall -Wextra -Werror -Iinclude
SRC = src/main.c src/cart.c src/discount.c src/state.c
BIN_DIR = bin
TARGET = $(BIN_DIR)/demo_app

.PHONY: all run clean

all: $(TARGET)

$(TARGET): $(SRC)
	@mkdir -p $(BIN_DIR)
	$(CC) $(CFLAGS) $(SRC) -o $(TARGET)

run: $(TARGET)
	./$(TARGET)

clean:
	rm -rf $(BIN_DIR)
