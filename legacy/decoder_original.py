#!/usr/bin/env python3
"""
lsb_steg_cli.py — меню Encrypt / Decrypt / Quit без паролей.

• 6 бит на пиксель (2 LSB из каналов R-G-B)
• длина сообщения (24 бита) в первых 4 пикселях
• сообщение — с «нулевым» выравниванием, начинается с пикселя № 5
"""

import cv2
import numpy as np
import os
import sys

# ────────────────────────── вспомогательные функции ──────────────────────────
def put_bits_into_pixel(px, six_bits: str):
    """Записываем 6 бит ('010101') в R-, G-, B-каналы пикселя."""
    px[2] &= 0b11111100  # R
    px[1] &= 0b11111100  # G
    px[0] &= 0b11111100  # B
    px[2] |= int(six_bits[0:2], 2)
    px[1] |= int(six_bits[2:4], 2)
    px[0] |= int(six_bits[4:6], 2)


def export_bits_from_pixel(px) -> str:
    """Читаем 2 LSB из R-, G-, B-каналов → строка '010101'."""
    return f"{px[2] & 3:02b}{px[1] & 3:02b}{px[0] & 3:02b}"


def build_message_bin(message: str) -> str:
    """Упаковка: после каждого символа добавляем нули до кратности 6."""
    msg_bin = ""
    for ch in message:
        msg_bin += f"{ord(ch):08b}"
        msg_bin = ("0" * ((6 - len(msg_bin) % 6) % 6)) + msg_bin
    return msg_bin


# ───────────────────────────── шифрование ────────────────────────────────────
def encrypt(image_path: str, text_path: str) -> str:
    img = cv2.imread(image_path, cv2.IMREAD_COLOR)
    if img is None:
        raise FileNotFoundError(f"Не удалось открыть изображение: {image_path}")

    with open(text_path, "r", encoding="utf-8") as f:
        message = f.read()

    h, w, _ = img.shape
    if 4 + 1 + 2 * len(message) > h * w:
        raise ValueError("Изображение слишком маленькое для такого сообщения.")

    flat = img.reshape(-1, 3)

    # длина (24 бита)
    len_bin = f"{len(message):024b}"
    for i in range(0, 24, 6):
        put_bits_into_pixel(flat[i // 6], len_bin[i:i + 6])

    # сообщение
    msg_bits = build_message_bin(message)
    px_idx = 5
    for i in range(0, len(msg_bits), 6):
        put_bits_into_pixel(flat[px_idx], msg_bits[i:i + 6])
        px_idx += 1

    out_name = f"encrypted_{os.path.splitext(os.path.basename(image_path))[0]}.png"
    cv2.imwrite(out_name, img)
    return out_name


# ──────────────────────────── дешифровка ─────────────────────────────────────
def decrypt(image_path: str) -> str:
    img = cv2.imread(image_path, cv2.IMREAD_COLOR)
    if img is None:
        raise FileNotFoundError(f"Не удалось открыть изображение: {image_path}")

    flat = img.reshape(-1, 3)

    msg_len = int("".join(export_bits_from_pixel(flat[i]) for i in range(4)), 2)
    if msg_len == 0 or 5 + 2 * msg_len > flat.shape[0]:
        raise ValueError("Повреждённые данные или несоответствие формату.")

    msg_bits = "".join(
        export_bits_from_pixel(flat[i]) for i in range(5, 5 + 2 * msg_len)
    )
    useful_bits = msg_bits[-msg_len * 8:]

    return "".join(
        chr(int(useful_bits[i : i + 8], 2)) for i in range(0, len(useful_bits), 8)
    )


# ────────────────────────────── CLI-меню ─────────────────────────────────────
def menu():
    print("╭─ Steganography CLI ──────────────")
    print("│ 1 — Encrypt text into image")
    print("│ 2 — Decrypt text from image")
    print("│ 3 — Quit")
    print("╰───────────────────────────────────")

    while True:
        try:
            choice = int(input("Выберите действие (1/2/3): "))
        except ValueError:
            print("Введите 1, 2 или 3.")
            continue

        if choice == 1:        # ENCRYPT
            img_name = input("  Исходное изображение (PNG/BMP): ").strip()
            txt_name = input("  Файл с текстом для шифрования: ").strip()
            try:
                out_file = encrypt(img_name, txt_name)
                print(f"✔ Готово! Сохранено в: {out_file}")
            except Exception as e:
                print(f"⚠ Ошибка: {e}")

        elif choice == 2:      # DECRYPT
            img_name = input("  Зашифрованное изображение: ").strip()
            try:
                message = decrypt(img_name)
                export_name = f"{img_name}_export.txt"
                with open(export_name, "w", encoding="utf-8") as f:
                    f.write(message)
                print(f"✔ Сообщение извлечено! Сохранено в {export_name}")
                print("─────────────────────────────")
                print(message)
                print("─────────────────────────────")
            except Exception as e:
                print(f"⚠ Ошибка: {e}")

        elif choice == 3:
            print("До свидания!")
            sys.exit(0)
        else:
            print("Введите 1, 2 или 3.")


if __name__ == "__main__":
    try:
        menu()
    except KeyboardInterrupt:
        print("\nПрервано пользователем.")
