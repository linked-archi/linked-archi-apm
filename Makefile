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
        skills install-local uninstall-local link-cli unlink-cli dist version bump \
        release-notes release-check clean docs docs-serve

help:
	@echo "check          validate skills and run the tests"
	@echo "test           run the test suite (verbose)"
	@echo "test-quiet     run the test suite (summary only)"
	@echo "skills         validate SKILL.md frontmatter"
	@echo "dist           archive the committed package directly"
	@echo "version        print the manifest version"
	@echo "bump           set the version everywhere it is repeated (TO=X.Y.Z)"
	@echo "release-notes  print the CHANGELOG section for that version"
	@echo "release-check  clean-tree, notes and test preflight before tagging"
	@echo "install-local  symlink committed skill directories into SKILLS_DIR"
	@echo "uninstall-local remove those symlinks"
	@echo "link-cli       symlink the repository la-kg dispatcher into BIN_DIR"
	@echo "docs           build the documentation site (strict)"
	@echo "docs-serve     serve the documentation site locally"
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

# The same command CI runs. --strict fails on a broken internal link rather than publishing
# one, and tests/test_docs.py checks the countable claims against catalog.json and
# patterns.json - the site states "39 templates" and "nine patterns" in prose, and prose is
# where a number goes stale first.
docs:
	$(PY) -m mkdocs build --strict

docs-serve:
	$(PY) -m mkdocs serve

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
	@for item in apm.yml LICENSE NOTICE README.md USAGE.md ADAPTING.md CHANGELOG.md \
	             CONTRIBUTING.md SECURITY.md PROPOSAL.md Makefile bin fixtures tests skills; do \
	  COPYFILE_DISABLE=1 cp -R "$$item" dist/linked-archi-apm/; \
	done
	@find dist/linked-archi-apm -name __pycache__ -type d -prune -exec rm -rf {} + 2>/dev/null || true
	@find dist/linked-archi-apm \( -name '._*' -o -name .DS_Store -o -name '*.py[co]' \) -type f -delete
	@COPYFILE_DISABLE=1 tar -czf "dist/linked-archi-apm-$(VERSION).tar.gz" -C dist linked-archi-apm
	@rm -rf dist/linked-archi-apm
	@echo "  dist/linked-archi-apm-$(VERSION).tar.gz"

# Prints the version alone, for a caller that needs to compare it with something. CI uses
# it to refuse a tag that disagrees with the manifest.
version:
	@echo "$(VERSION)"

# The version is repeated outside the manifest, in places that cannot be derived at read
# time: `metadata.version` in each SKILL.md - the only version an installed skill carries,
# since apm.yml is not deployed into a harness - and the install pin readers copy out of
# README.md and USAGE.md. Ten copies were two releases stale before this existed.
#
# TO, not VERSION: VERSION is an override for reading the manifest, and a bump is a write.
bump:
	@test -n "$(TO)" || { echo "usage: make bump TO=X.Y.Z" >&2; exit 1; }
	@$(PY) tests/version_sync.py --set "$(TO)"
	@echo "  now write the CHANGELOG section for $(TO), which release-check requires"

# The CHANGELOG section for VERSION, which is what the release workflow publishes.
#
# An absent section is an error rather than an empty release body. A release nobody
# wrote notes for is a release nobody can read, and the failure has to land here - before
# the tag - rather than in a published artifact.
# Three stops, not one. The next `## [` ends the section; a link-reference definition
# (`[0.1.0]: https://...`) ends it too, because the oldest section is followed by the
# footer rather than by another heading and those definitions would otherwise be
# published as the tail of the release body. Then leading and trailing blank lines are
# trimmed, so the body starts at the first word.
release-notes:
	@notes=$$(awk -v v="$(VERSION)" \
	  '$$0 ~ "^## \\[" v "\\]" {found=1; next} \
	   found && (/^## \[/ || /^\[[^]]+\]: /) {exit} \
	   found {print}' CHANGELOG.md \
	  | sed -e '/./,$$!d' \
	  | awk 'NF{last=NR} {line[NR]=$$0} END{for(i=1;i<=last;i++) print line[i]}'); \
	if [ -z "$$(printf '%s' "$$notes" | tr -d '[:space:]')" ]; then \
	  echo "REFUSED: CHANGELOG.md has no section for $(VERSION)." >&2; \
	  echo "  Add '## [$(VERSION)] - YYYY-MM-DD' with what changed, then retry." >&2; \
	  exit 1; \
	fi; \
	printf '%s\n' "$$notes"

release-check: check
	@printf '\n'
	@if [ -n "$$(git status --porcelain)" ]; then \
	  echo "REFUSED: working tree is dirty. Commit or stash first:"; \
	  git status --short | sed 's/^/    /'; exit 1; \
	fi
	@echo "  working tree clean"
	@echo "  version: $(VERSION)"
	@$(MAKE) --no-print-directory release-notes >/dev/null
	@echo "  release notes: $$($(MAKE) --no-print-directory release-notes | wc -l | tr -d ' ') lines from CHANGELOG.md"
	@printf 'Ready:\n'
	@printf '  make dist\n'
	@printf '  git tag -a v$(VERSION) -m "v$(VERSION)"\n'
	@printf '  git push origin v$(VERSION)\n'
	@printf '\nThe tag must be annotated: APM refuses a lightweight tag when it refreshes a\n'
	@printf 'full-SHA revision pin, so a lightweight v$(VERSION) installs but never offers itself\n'
	@printf 'as an upgrade. Pushing it runs CI and publishes the GitHub release.\n'

clean:
	find . -name __pycache__ -type d -prune -exec rm -rf {} +
	rm -f *.rendered.rq *.results.json
	rm -rf dist
