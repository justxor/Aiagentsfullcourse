# Полный инженерный курс по AI-агентам — единая точка входа.
# Все команды курса живут здесь. Одна команда - одно осмысленное действие.

SHELL := /bin/bash
.DEFAULT_GOAL := help

PY      ?= python3
VENV    ?= .venv
RUNS    ?= 5
WORKERS ?= 4
SUITE   ?= main
LAB     ?=
RUN     ?= last

.PHONY: help doctor install lab check hint solution diff eval eval-compare \
        eval-report eval-baseline-update cost trace test lint types \
        sandbox-build sandbox-test agent-ws agent-ws-diff agent-ws-clean \
        injections policy-test clean ci

## ------------------------------------------------------------------ ##
## Справка
## ------------------------------------------------------------------ ##

help:  ## показать список команд
	@grep -hE '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) \
		| awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-24s\033[0m %s\n", $$1, $$2}'
	@echo ""
	@echo "  Примеры:"
	@echo "    make doctor                       проверить окружение"
	@echo "    make lab LAB=lab01                запустить лабораторную"
	@echo "    make check LAB=lab01              проверить приёмку лабораторной"
	@echo "    make eval SUITE=smoke RUNS=3      быстрый прогон эвалов"
	@echo "    make cost RUN=last                стоимость последнего прогона"
	@echo "    make trace RUN=r-2f8a             разобрать прогон"

## ------------------------------------------------------------------ ##
## Окружение
## ------------------------------------------------------------------ ##

doctor:  ## проверить окружение: python, docker, ключи, права, модель
	@$(PY) tools/doctor.py

install:  ## создать venv и установить зависимости
	@$(PY) -m venv $(VENV)
	@$(VENV)/bin/pip install -q -U pip
	@$(VENV)/bin/pip install -q -r requirements.txt
	@echo "готово: source $(VENV)/bin/activate"

## ------------------------------------------------------------------ ##
## Лабораторные
## ------------------------------------------------------------------ ##

lab:  ## запустить лабораторную: make lab LAB=lab01 [TASK="..."]
	@test -n "$(LAB)" || (echo "укажи LAB=lab01"; exit 1)
	@$(PY) -m labs.$(LAB).starter.main $(if $(TASK),--task "$(TASK)",)

check:  ## проверка приёмки: make check LAB=lab01  (или make check m04 для модуля)
	@test -n "$(LAB)" || (echo "укажи LAB=lab01 или m04"; exit 1)
	@$(PY) -m pytest -q labs/$(LAB)/tests

hint:  ## следующая подсказка по лабораторной
	@$(PY) tools/hint.py $(LAB)

solution:  ## показать эталон (только после трёх попыток)
	@$(PY) tools/solution.py $(LAB)

diff:  ## сравнить своё решение с эталоном
	@diff -u labs/$(LAB)/starter labs/$(LAB)/solution || true

## ------------------------------------------------------------------ ##
## Эвалы и бенчмарки
## ------------------------------------------------------------------ ##

eval:  ## прогнать набор: make eval [SUITE=main] [RUNS=5] [FILTER=bugfix] [CASE=G17]
	@$(PY) benchmarks/runner/run.py \
		--suite benchmarks/suites/$(SUITE).yaml \
		--runs $(RUNS) --workers $(WORKERS) \
		$(if $(FILTER),--filter $(FILTER),) $(if $(CASE),--case $(CASE),) \
		--baseline benchmarks/baselines/$(SUITE).json

eval-compare:  ## парное сравнение: make eval-compare A=... B=...
	@$(PY) benchmarks/runner/compare.py --a $(A) --b $(B)

eval-report:  ## markdown-отчёт по последнему прогону
	@$(PY) benchmarks/runner/report.py --latest

eval-baseline-update:  ## обновить базовую линию (спросит подтверждение)
	@$(PY) benchmarks/runner/score.py --promote --suite $(SUITE)

injections:  ## прогнать набор сценариев безопасности
	@$(PY) benchmarks/runner/run.py \
		--suite benchmarks/suites/injection.yaml --runs 3 --strict

policy-test:  ## табличные тесты политики прав
	@$(PY) -m pytest -q tests/test_policy.py

## ------------------------------------------------------------------ ##
## Наблюдаемость
## ------------------------------------------------------------------ ##

trace:  ## разобрать прогон: make trace RUN=r-2f8a  (или RUN=last)
	@$(PY) tools/trace.py --run $(RUN)

cost:  ## стоимость прогона по шагам: make cost RUN=last
	@$(PY) tools/cost.py --run $(RUN)

## ------------------------------------------------------------------ ##
## Песочница
## ------------------------------------------------------------------ ##

sandbox-build:  ## собрать образ песочницы
	@docker build -f templates/docker/Dockerfile.sandbox -t agent-sandbox:latest .

sandbox-test:  ## негативные тесты изоляции (должны провалиться внутри)
	@bash templates/docker/sandbox_test.sh

WS ?= ws-$(shell date +%s)

agent-ws:  ## изолированный воркспейс: make agent-ws CMD="make test"
	@git worktree add -b agent/$(WS) ../$(WS) origin/main
	@mkdir -p ../.cache/$(WS)/pip
	@docker run --rm --name agent-$(WS) \
		--user 10001:10001 --read-only \
		--tmpfs /tmp:rw,noexec,nosuid,size=512m \
		-v "$(PWD)/../$(WS):/work:rw" \
		-v "$(PWD)/../.cache/$(WS)/pip:/home/agent/.cache/pip:rw" \
		--network none --cpus 2 --memory 4g --memory-swap 4g \
		--pids-limit 256 --cap-drop ALL --security-opt no-new-privileges \
		agent-sandbox:latest "$(CMD)"

agent-ws-diff:  ## посмотреть, что агент сделал в воркспейсе
	@git -C ../$(WS) diff origin/main

agent-ws-clean:  ## удалить воркспейс и ветку
	@-docker rm -f agent-$(WS) 2>/dev/null
	@git worktree remove --force ../$(WS) || true
	@git branch -D agent/$(WS) || true
	@rm -rf ../.cache/$(WS)

## ------------------------------------------------------------------ ##
## Качество кода
## ------------------------------------------------------------------ ##

test:  ## юнит-тесты
	@$(PY) -m pytest -q

lint:  ## линтер
	@ruff check .

types:  ## проверка типов
	@mypy --ignore-missing-imports .

ci:  ## всё, что проверяет CI: ворота 1 и 2
	@$(MAKE) lint
	@$(MAKE) types
	@$(MAKE) test
	@$(MAKE) policy-test
	@$(MAKE) eval SUITE=smoke RUNS=3

clean:  ## удалить артефакты прогонов и кеши
	@rm -rf runs/*.jsonl .pytest_cache .mypy_cache .ruff_cache
	@find . -name '__pycache__' -type d -prune -exec rm -rf {} +
