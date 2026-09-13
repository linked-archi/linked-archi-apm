# linked-archi-apm
# `make check` validates the committed Agent Skills directly; there is no build step.

PY      ?= python3
SCRIPTS := skills/linked-archi-source/scripts:skills/linked-archi-profile/scripts:skills/linked-archi-connect/scripts:skills/linked-archi-query/scripts:skills/linked-archi-validate/scripts:skills/linked-archi-analyse/scripts
PYPATH  := PYTHONPATH=$(SCRIPTS)
# Maintainer-only. `make fixtures` re-extracts from real converter output, which means a
# checkout of the converters and of linked-archi-meta alongside this repo. A consumer never
# needs it: the fixtures are committed. Override when your checkouts sit elsewhere.
CONV    ?= ../converters/example-architecture-project
BASE_IRI?= https://example.org/la/
SKILLS_DIR ?= $(HOME)/.kiro/skills
BIN_DIR ?= $(HOME)/.local/bin

.PHONY: help check test test-quiet catalog profile verify verify-curated fixtures \
        skills install-local uninstall-local link-cli unlink-cli dist release-check clean

help:
	@echo "check          validate skills and run the tests"
	@echo "test           run the test suite (verbose)"
	@echo "test-quiet     run the test suite (summary only)"
	@echo "skills         validate SKILL.md frontmatter"
	@echo "dist           archive the committed package directly"
	@echo "release-check  clean-tree and test preflight before tagging"
	@echo "install-local  symlink committed skill directories into SKILLS_DIR"
	@echo "uninstall-local remove those symlinks"
	@echo "link-cli       symlink the repository la-kg dispatcher into BIN_DIR"
	@echo "catalog        list query templates"
	@echo "profile        show the default profile"
	@echo "verify         verify the default profile against the base fixture"
	@echo "verify-curated verify the curated profile against augmented.trig"
	@echo "fixtures       regenerate fixtures from converter output"
	@echo "               (converter-1.3.trig is a separate step: it needs the"
	@echo "                converter jars - see fixtures/PROVENANCE.md)"

check: skills test

# Installation links exactly what is committed. It never generates or copies runtime.
install-local:
	@mkdir -p "$(SKILLS_DIR)"
	@for s in skills/*/; do \
	  name=$$(basename "$$s"); target="$(SKILLS_DIR)/$$name"; \
	  if [ -d "$$target" ] && [ ! -L "$$target" ]; then \
	    echo "  REFUSED $$name: $$target is a real directory"; \
	    if [ "$(FORCE)" != "1" ]; then continue; fi; \
	    rm -rf "$$target"; \
	  fi; \
	  rm -f "$$target"; ln -s "$(CURDIR)/skills/$$name" "$$target"; \
	  echo "  linked $$name -> $$target"; \
	done

uninstall-local:
	@for s in skills/*/; do \
	  name=$$(basename "$$s"); \
	  if [ -L "$(SKILLS_DIR)/$$name" ]; then rm "$(SKILLS_DIR)/$$name"; echo "  unlinked $$name"; \
	  elif [ -d "$(SKILLS_DIR)/$$name" ]; then echo "  SKIPPED $$name: real directory"; fi; \
	done

link-cli:
	@mkdir -p "$(BIN_DIR)"
	@ln -sf "$(CURDIR)/bin/la-kg" "$(BIN_DIR)/la-kg"
	@echo "  linked $(BIN_DIR)/la-kg -> $(CURDIR)/bin/la-kg"
	@case ":$$PATH:" in \
	  *":$(BIN_DIR):"*) ;; \
	  *) echo "  warning: $(BIN_DIR) is not on PATH"; \
	     echo '  Add to ~/.zshrc: export PATH="$(BIN_DIR):$$PATH"' ;; \
	esac

unlink-cli:
	@rm -f "$(BIN_DIR)/la-kg" && echo "  removed $(BIN_DIR)/la-kg"

test:
	$(PYPATH) $(PY) -m unittest discover -s tests -t . -v

test-quiet:
	$(PYPATH) $(PY) -m unittest discover -s tests -t .

skills:
	$(PY) tests/validate_skills.py

catalog:
	skills/linked-archi-query/scripts/la-query catalog list

profile:
	skills/linked-archi-profile/scripts/la-profile show --profile linked-archi-default

verify:
	skills/linked-archi-profile/scripts/la-profile verify \
	  --profile linked-archi-default --data fixtures/base.trig

verify-curated:
	skills/linked-archi-profile/scripts/la-profile verify \
	  --profile curated-store --data fixtures/augmented.trig

# Maintainer-only, and it says so rather than failing on a missing path. The fixtures are
# committed; a consumer has no reason to rebuild them and no checkout to rebuild them from.
fixtures:
	@test -d "$(CONV)" || { \
	  echo "make fixtures needs the converters checked out alongside this repo."; \
	  echo "  looked for: $(CONV)"; \
	  echo "  override:   make fixtures CONV=/path/to/example-architecture-project"; \
	  echo "The committed fixtures under fixtures/ are the released artifact - you only"; \
	  echo "need this target when re-extracting from new converter output."; \
	  exit 1; }
	$(PY) fixtures/build_fixtures.py

# Reads the manifest version. The authoring spec wants it quoted in YAML so it cannot parse
# as a number, and those quotes must not reach the tarball name - hence the strip. Written
# without nested quote literals because this is a Make recipe inside a shell inside Python.
VERSION ?= $(shell $(PY) -c "import re,pathlib;m=re.search(r'^version:\s*(\S+)',pathlib.Path('apm.yml').read_text(),re.M);print(m.group(1).strip(chr(34)+chr(39)))")

dist: check
	@rm -rf dist/linked-archi-apm && mkdir -p dist/linked-archi-apm
	@for item in apm.yml LICENSE NOTICE README.md USAGE.md ADAPTING.md \
	             CONTRIBUTING.md SECURITY.md PROPOSAL.md Makefile bin fixtures tests skills; do \
	  COPYFILE_DISABLE=1 cp -R "$$item" dist/linked-archi-apm/; \
	done
	@find dist/linked-archi-apm -name __pycache__ -type d -prune -exec rm -rf {} + 2>/dev/null || true
	@find dist/linked-archi-apm \( -name '._*' -o -name .DS_Store -o -name '*.py[co]' \) -type f -delete
	@COPYFILE_DISABLE=1 tar -czf "dist/linked-archi-apm-$(VERSION).tar.gz" -C dist linked-archi-apm
	@rm -rf dist/linked-archi-apm
	@echo "  dist/linked-archi-apm-$(VERSION).tar.gz"

release-check: check
	@printf '\n'
	@if [ -n "$$(git status --porcelain)" ]; then \
	  echo "REFUSED: working tree is dirty. Commit or stash first:"; \
	  git status --short | sed 's/^/    /'; exit 1; \
	fi
	@echo "  working tree clean"
	@echo "  version: $(VERSION)"
	@echo "Ready: make dist && git tag v$(VERSION) && git push --tags"

clean:
	find . -name __pycache__ -type d -prune -exec rm -rf {} +
	rm -f *.rendered.rq *.results.json
	rm -rf dist
