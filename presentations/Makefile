# Dyson Labs Presentations
#
# Builds audience-specific presentations from modular markdown slides.
# Uses reveal-md with Mermaid support.
#
# Requirements:
#   npm install -g reveal-md
#
# Usage:
#   make all          - Build all presentations
#   make serve-nasa   - Live preview NASA deck
#   make clean        - Remove generated files

.PHONY: all clean nasa darpa commercial serve serve-nasa serve-darpa serve-commercial help

# Common slides (in order) - edit this list to reorder or insert slides
# Note: Payment details only in commercial deck
COMMON_SLIDES := \
	common/title.md \
	common/problem.md \
	common/vision.md \
	common/sisl.md \
	common/scap.md \
	common/delegation.md \
	common/architecture.md \
	common/security.md \
	common/demo.md \
	common/roadmap.md \
	common/implementation.md \
	common/risks.md \
	common/summary.md

# Audience-specific slides - edit to reorder or add slides per audience
NASA_SLIDES := \
	nasa/ccsds_alignment.md \
	nasa/trl_progression.md \
	nasa/cta.md

DARPA_SLIDES := \
	darpa/contested_env.md \
	darpa/cta.md

COMMERCIAL_SLIDES := \
	commercial/business_model.md \
	common/payment.md \
	commercial/market.md \
	commercial/cta.md

# Output files
OUTPUTS := dyson-nasa.html dyson-darpa.html dyson-commercial.html

# reveal-md options with Mermaid support
REVEAL_OPTS := --theme black --highlight-theme monokai --css _theme.css \
	--scripts "https://cdn.jsdelivr.net/npm/mermaid@10/dist/mermaid.min.js,mermaid-init.js" \
	--static-dirs=.

# Separator between slides (reveal-md uses --- for horizontal, ---- for vertical)
define SLIDE_SEP


---

endef

all: $(OUTPUTS)
	@echo "Built all presentations:"
	@ls -la *.html 2>/dev/null || true

# Concatenate markdown files with slide separators
.tmp-nasa.md: $(COMMON_SLIDES) $(NASA_SLIDES)
	@echo "Assembling NASA slides..."
	@rm -f $@
	@for f in $(COMMON_SLIDES) $(NASA_SLIDES); do \
		cat $$f >> $@; \
		echo "" >> $@; \
		echo "---" >> $@; \
		echo "" >> $@; \
	done

.tmp-darpa.md: $(COMMON_SLIDES) $(DARPA_SLIDES)
	@echo "Assembling DARPA slides..."
	@rm -f $@
	@for f in $(COMMON_SLIDES) $(DARPA_SLIDES); do \
		cat $$f >> $@; \
		echo "" >> $@; \
		echo "---" >> $@; \
		echo "" >> $@; \
	done

.tmp-commercial.md: $(COMMON_SLIDES) $(COMMERCIAL_SLIDES)
	@echo "Assembling Commercial slides..."
	@rm -f $@
	@for f in $(COMMON_SLIDES) $(COMMERCIAL_SLIDES); do \
		cat $$f >> $@; \
		echo "" >> $@; \
		echo "---" >> $@; \
		echo "" >> $@; \
	done

# Build HTML from assembled markdown
dyson-nasa.html: .tmp-nasa.md _theme.css
	@echo "Building $@..."
	reveal-md .tmp-nasa.md $(REVEAL_OPTS) --static $@ --static-dirs=. 2>/dev/null || \
	reveal-md .tmp-nasa.md $(REVEAL_OPTS) --print $@

dyson-darpa.html: .tmp-darpa.md _theme.css
	@echo "Building $@..."
	reveal-md .tmp-darpa.md $(REVEAL_OPTS) --static $@ --static-dirs=. 2>/dev/null || \
	reveal-md .tmp-darpa.md $(REVEAL_OPTS) --print $@

dyson-commercial.html: .tmp-commercial.md _theme.css
	@echo "Building $@..."
	reveal-md .tmp-commercial.md $(REVEAL_OPTS) --static $@ --static-dirs=. 2>/dev/null || \
	reveal-md .tmp-commercial.md $(REVEAL_OPTS) --print $@

# Individual targets
nasa: dyson-nasa.html
darpa: dyson-darpa.html
commercial: dyson-commercial.html

# Live preview servers
serve-nasa: .tmp-nasa.md _theme.css
	@echo "Starting NASA preview at http://localhost:1948"
	reveal-md .tmp-nasa.md $(REVEAL_OPTS) --watch

serve-darpa: .tmp-darpa.md _theme.css
	@echo "Starting DARPA preview at http://localhost:1948"
	reveal-md .tmp-darpa.md $(REVEAL_OPTS) --watch

serve-commercial: .tmp-commercial.md _theme.css
	@echo "Starting Commercial preview at http://localhost:1948"
	reveal-md .tmp-commercial.md $(REVEAL_OPTS) --watch

# Serve base slides only (for quick iteration)
serve:
	@echo "Starting base slides preview..."
	@cat $(COMMON_SLIDES) > .tmp-base.md
	reveal-md .tmp-base.md $(REVEAL_OPTS) --watch

clean:
	rm -rf dyson-nasa.html dyson-darpa.html dyson-commercial.html .tmp-*.md _static
	@echo "Cleaned generated files"

help:
	@echo "Dyson Labs Presentations"
	@echo ""
	@echo "Source structure:"
	@echo "  common/     - Shared slides (title.md, problem.md, vision.md, ...)"
	@echo "  nasa/       - NASA-specific slides"
	@echo "  darpa/      - DARPA-specific slides"
	@echo "  commercial/ - Investor-specific slides"
	@echo "  stories/    - User story slides (not in default builds)"
	@echo "  _theme.css  - Custom styling"
	@echo "  mermaid-init.js - Mermaid diagram initialization"
	@echo ""
	@echo "Build targets:"
	@echo "  make all             - Build all HTML presentations"
	@echo "  make nasa            - Build NASA deck only"
	@echo "  make darpa           - Build DARPA deck only"
	@echo "  make commercial      - Build Commercial deck only"
	@echo ""
	@echo "Preview targets:"
	@echo "  make serve           - Preview base slides"
	@echo "  make serve-nasa      - Preview NASA deck with hot reload"
	@echo "  make serve-darpa     - Preview DARPA deck"
	@echo "  make serve-commercial - Preview Commercial deck"
	@echo ""
	@echo "  make clean           - Remove generated files"
	@echo ""
	@echo "Requirements: npm install -g reveal-md"
