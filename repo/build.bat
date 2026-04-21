@echo off
set BIN_DIR=bin
set TARGET=%BIN_DIR%\demo_app.exe

if not exist "%BIN_DIR%" mkdir "%BIN_DIR%"

echo Compiling with clang...
clang -std=c11 -Wall -Wextra -Werror -Iinclude src\main.c src\cart.c src\discount.c src\state.c -o "%TARGET%"

if %ERRORLEVEL% equ 0 (
    echo Compilation successful. Running demo_app.exe...
    "%TARGET%"
) else (
    echo Compilation failed!
)
