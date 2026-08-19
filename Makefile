.PHONY: default all clear install acquire curate publish

default: curate publish

RAW_DATA_DIR           := .dev/data/raw/
NORMALIZED_DATA_DIR    := .dev/data/normalized/
CURATED_DATA_DIR       := .dev/data/curated/
CURATED_DATA_CACHE_DIR := .dev/data/cache/
# Mirrors config.py: env var set -> <root>/data/ (root is a foreign checkout, e.g. htmlspec);
# unset -> local .dev/data/dist/.
DIST_DATA_DIR          := $(if $(DIST_DATA_DIR),$(DIST_DATA_DIR)/,.dev/data/dist/)
DIST_CONTENT_HASH_FILE := $(CURATED_DATA_CACHE_DIR)dist_content.sha256

DATA_DIRS := $(RAW_DATA_DIR) $(NORMALIZED_DATA_DIR) $(CURATED_DATA_DIR) $(CURATED_DATA_CACHE_DIR) $(DIST_DATA_DIR)
DATA_DIRS_RM := $(NORMALIZED_DATA_DIR) $(CURATED_DATA_DIR) $(CURATED_DATA_CACHE_DIR)

specs      := indices.html dom.html input.html syntax.html
spec_etags := $(addprefix $(RAW_DATA_DIR), $(specs:.html=.etag))
spec_times := $(addprefix $(RAW_DATA_DIR), $(specs:.html=.time))
all_specs  := $(addprefix $(RAW_DATA_DIR), $(specs))
all_times  := $(spec_times) $(RAW_DATA_DIR)aria.time

GREEN  := \033[0;32m
YELLOW := \033[0;33m
NC     := \033[0m

define say
	@printf "$(YELLOW)MAKE:%s$(NC)\n" "$(1)"
endef

define confirm
	@printf "$(GREEN)MAKE: ✅%s$(NC)\n" "$(1)"
endef

all: acquire curate publish

clear:
	rm --force --recursive $(DATA_DIRS_RM)

install:
	python3 -m pip install -e .

# --- Phony entry points ---
# These always run their recipe, giving a final "step complete" confirmation
# after their dependencies are resolved (or skipped if up-to-date).

publish: $(DIST_CONTENT_HASH_FILE) | $(DIST_DATA_DIR)
	$(call confirm, Publishing and all preceding steps complete (see $(DIST_DATA_DIR)manifest.json).)

curate: $(CURATED_DATA_DIR)manifest.json | $(CURATED_DATA_DIR)
	$(call confirm, Acquiring and curating complete (see $(CURATED_DATA_DIR)manifest.json))

acquire: $(RAW_DATA_DIR)manifest.json | $(RAW_DATA_DIR)
	$(call confirm, Acquiring completed; collected all last‑modified timestamps in $(RAW_DATA_DIR)manifest.json.)

# --- Build rules ---

$(DIST_CONTENT_HASH_FILE): $(CURATED_DATA_DIR)manifest.json | $(CURATED_DATA_CACHE_DIR)
	$(call say, 📦 Publishing $(DIST_DATA_DIR) files...)
	@python3 src/publish.py

$(CURATED_DATA_DIR)manifest.json: $(RAW_DATA_DIR)manifest.json
	$(call say, 🧲 Extracting and curating raw HTML into typed NDJSON + manifest under $(CURATED_DATA_DIR)...)
	@python3 src/curate.py

$(DATA_DIRS): %/:
	@mkdir -p $@

$(RAW_DATA_DIR)aria.html: | $(RAW_DATA_DIR)
	@touch $(RAW_DATA_DIR)aria.etag
	$(call say, 📥 Acquiring ARIA specification from https://w3c.github.io/aria/...)
	@curl --silent --show-error --fail \
	      --etag-compare $(RAW_DATA_DIR)aria.etag --etag-save $(RAW_DATA_DIR)aria.etag \
	      --dump-header $(RAW_DATA_DIR)aria.headers \
	      --output $@ \
	      https://w3c.github.io/aria/
	@grep --ignore-case '^last-modified:' $(RAW_DATA_DIR)aria.headers \
	    | sed 's/^[Ll]ast-[Mm]odified: //;s/\r$$//' \
	    > $(RAW_DATA_DIR)aria.time.new
	@if [ -s $(RAW_DATA_DIR)aria.time.new ]; then mv $(RAW_DATA_DIR)aria.time.new $(RAW_DATA_DIR)aria.time; \
	                                   else rm --force $(RAW_DATA_DIR)aria.time.new; fi
	@rm --force $(RAW_DATA_DIR)aria.headers

$(RAW_DATA_DIR)%.html: | $(RAW_DATA_DIR)
	$(call say, 📥 Acquiring HTML specification from https://html.spec.whatwg.org/multipage/$*.html...)
	@touch $(RAW_DATA_DIR)$*.etag
	@curl --silent --show-error --fail \
	     --etag-compare $(RAW_DATA_DIR)$*.etag --etag-save $(RAW_DATA_DIR)$*.etag \
	     --dump-header $(RAW_DATA_DIR)$*.headers \
	     --output $@ \
	     https://html.spec.whatwg.org/multipage/$*.html
	@grep --ignore-case '^last-modified:' $(RAW_DATA_DIR)$*.headers | sed 's/^[Ll]ast-[Mm]odified: //;s/\r$$//' \
	     > $(RAW_DATA_DIR)$*.time.new
	@if [ -s $(RAW_DATA_DIR)$*.time.new ]; then mv $(RAW_DATA_DIR)$*.time.new $(RAW_DATA_DIR)$*.time; \
	                                 else rm --force $(RAW_DATA_DIR)$*.time.new; fi
	@rm --force $(RAW_DATA_DIR)$*.headers

$(RAW_DATA_DIR)manifest.json: $(all_specs) $(RAW_DATA_DIR)aria.html
	@{ \
	    echo '{'; \
	    i=0; \
	    total=$(words $(all_times)); \
	    for f in $(all_times); do \
	        i=$$((i + 1)); \
	        name=$${f%.time}; \
	        name=$${name##*/};          # MAKE: strip directory, keep only filename \
	        printf '  "%s": "%s"' "$$name" "$$(cat $$f)"; \
	        [ $$i -lt $$total ] && echo ',' || echo; \
	    done; \
	    echo '}'; \
	} > $@
