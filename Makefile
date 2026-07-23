# Local development helpers.
#
# The system Ruby on macOS is 2.6, which can no longer resolve this site's
# gems (modern nokogiri requires Ruby >= 3.0). Homebrew's ruby@3.4 is keg-only,
# so it is not on PATH by default. These targets put it on PATH for you.
#
#   make serve         # build + serve on http://localhost:4000
#   make build         # one-off build into _site/
#   make publications  # refresh _data/publications.yml from the APIs
#   make clean         # remove build output
#
# Nothing here talks to git.

RUBY_PREFIX := $(shell brew --prefix ruby@3.4 2>/dev/null)
ifeq ($(RUBY_PREFIX),)
RUBY_PREFIX := /opt/homebrew/opt/ruby@3.4
endif

BUNDLE := PATH="$(RUBY_PREFIX)/bin:$$PATH" bundle
PORT ?= 4000

# Repository slug, needed by jekyll-github-metadata in production builds.
REPO ?= seyyaw/seyyaw.github.io

.PHONY: help serve build publications clean install check-ruby

help:
	@echo "make serve         - serve the site at http://localhost:$(PORT)"
	@echo "make build         - build the site into _site/"
	@echo "make build-prod    - production build (as deployed) into _site_prod/"
	@echo "make publications  - refresh _data/publications.yml"
	@echo "make clean         - remove _site/"

check-ruby:
	@test -x "$(RUBY_PREFIX)/bin/ruby" || { \
		echo "Ruby 3.4 not found at $(RUBY_PREFIX)."; \
		echo "Install it with:  brew install ruby@3.4"; \
		exit 1; }
	@echo "Using $$($(RUBY_PREFIX)/bin/ruby -v)"

# Install gems into vendor/bundle only when they are missing or out of date.
install: check-ruby
	@$(BUNDLE) config set --local path vendor/bundle >/dev/null 2>&1 || true
	@$(BUNDLE) check >/dev/null 2>&1 || $(BUNDLE) install

# LiveReload gets its own port derived from PORT, so a second `make serve` on a
# different port does not collide with an instance that is already running.
serve: install
	$(BUNDLE) exec jekyll serve --port $(PORT) \
		--livereload --livereload-port $$(( $(PORT) + 31729 ))

build: install
	$(BUNDLE) exec jekyll build

# Production build. GitHub Pages sets JEKYLL_ENV=production, which enables the
# HTML compressor; that strips newlines, so inline scripts must not use //
# comments. Use this target to reproduce the deployed output locally.
build-prod: install
	JEKYLL_ENV=production PAGES_REPO_NWO=$(REPO) $(BUNDLE) exec jekyll build -d _site_prod

publications:
	python3 scripts/fetch_publications.py

clean:
	rm -rf _site _site_prod
