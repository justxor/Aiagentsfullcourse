import random
import os
import sys


class Minesweeper:
    def __init__(self, rows=10, cols=10, mines=15):
        self.rows = rows
        self.cols = cols
        self.mines = mines
        self.board = [[' ' for _ in range(cols)] for _ in range(rows)]
        self.revealed = [[False for _ in range(cols)] for _ in range(rows)]
        self.flagged = [[False for _ in range(cols)] for _ in range(rows)]
        self.game_over = False
        self.won = False
        self.first_move = True
        self.place_mines()
        self.calculate_numbers()

    def place_mines(self):
        positions = [(r, c) for r in range(self.rows) for c in range(self.cols)]
        mine_positions = random.sample(positions, self.mines)
        for r, c in mine_positions:
            self.board[r][c] = '*'

    def calculate_numbers(self):
        for r in range(self.rows):
            for c in range(self.cols):
                if self.board[r][c] == '*':
                    continue
                count = 0
                for dr in (-1, 0, 1):
                    for dc in (-1, 0, 1):
                        if dr == 0 and dc == 0:
                            continue
                        nr, nc = r + dr, c + dc
                        if 0 <= nr < self.rows and 0 <= nc < self.cols:
                            if self.board[nr][nc] == '*':
                                count += 1
                if count > 0:
                    self.board[r][c] = str(count)

    def clear_screen(self):
        os.system('cls' if os.name == 'nt' else 'clear')

    def display(self, show_all=False):
        self.clear_screen()
        print("  " + " ".join(f"{i % 10}" for i in range(self.cols)))
        print("  +" + "--" * self.cols + "-+")
        for r in range(self.rows):
            row_cells = []
            for c in range(self.cols):
                if self.revealed[r][c] or show_all:
                    if self.board[r][c] == '*':
                        row_cells.append("*")
                    elif self.board[r][c] == ' ':
                        row_cells.append(" ")
                    else:
                        row_cells.append(self.board[r][c])
                elif self.flagged[r][c]:
                    row_cells.append("F")
                else:
                    row_cells.append(".")
            print(f"{r:2}|" + "".join(f" {cell}" for cell in row_cells) + " |")
        print("  +" + "--" * self.cols + "-+")
        print("Команды:")
        print("  r <строка> <столбец> — открыть клетку")
        print("  f <строка> <столбец> — поставить/убрать флаг")
        print("  q — выход")
        print(f"Осталось мин: {self.mines - sum(sum(row) for row in self.flagged)}")

    def reveal(self, r, c):
        if not (0 <= r < self.rows and 0 <= c < self.cols):
            return True
        if self.revealed[r][c] or self.flagged[r][c]:
            return True
        self.revealed[r][c] = True
        if self.board[r][c] == '*':
            self.game_over = True
            self.won = False
            return False
        if self.board[r][c] == ' ':
            for dr in (-1, 0, 1):
                for dc in (-1, 0, 1):
                    if dr == 0 and dc == 0:
                        continue
                    self.reveal(r + dr, c + dc)
        return True

    def toggle_flag(self, r, c):
        if not (0 <= r < self.rows and 0 <= c < self.cols):
            return
        if not self.revealed[r][c]:
            self.flagged[r][c] = not self.flagged[r][c]

    def check_win(self):
        for r in range(self.rows):
            for c in range(self.cols):
                if self.board[r][c] != '*' and not self.revealed[r][c]:
                    return False
        return True

    def play(self):
        while not self.game_over:
            self.display()
            try:
                cmd = input("> ").strip().split()
                if not cmd:
                    continue
                if cmd[0] == 'q':
                    print("Выход из игры.")
                    return
                if cmd[0] == 'r' and len(cmd) == 3:
                    r, c = int(cmd[1]), int(cmd[2])
                    if not self.reveal(r, c):
                        self.game_over = True
                    elif self.check_win():
                        self.game_over = True
                        self.won = True
                elif cmd[0] == 'f' and len(cmd) == 3:
                    r, c = int(cmd[1]), int(cmd[2])
                    self.toggle_flag(r, c)
                else:
                    print("Неверная команда. Пример: r 3 5 или f 3 5")
                    input("Нажмите Enter для продолжения...")
            except (ValueError, IndexError):
                print("Неверный ввод. Используйте: r <строка> <столбец> или f <строка> <столбец>")
                input("Нажмите Enter для продолжения...")
            except KeyboardInterrupt:
                print("\nВыход.")
                return

        self.display(show_all=True)
        if self.won:
            print("\nПОБЕДА! Вы открыли все безопасные клетки!")
        else:
            print("\nВЗРЫВ! Вы попали на мину!")


if __name__ == "__main__":
    game = Minesweeper(rows=10, cols=10, mines=15)
    game.play()
