document.addEventListener("DOMContentLoaded", () => {
    const links = Array.from(document.querySelectorAll(".po-navbar__link"));
    const sections = links
        .map((link) => document.querySelector(link.getAttribute("href")))
        .filter(Boolean);

    const highlightNav = () => {
        const offset = window.scrollY + window.innerHeight / 3;
        let activeId = sections[0]?.id;
        for (const section of sections) {
            if (section.offsetTop <= offset) {
                activeId = section.id;
            }
        }
        links.forEach((link) => {
            const targetId = link.getAttribute("href").replace("#", "");
            link.classList.toggle("is-active", targetId === activeId);
        });
    };

    highlightNav();
    window.addEventListener("scroll", highlightNav, { passive: true });

    // Simple carousel behaviour: clicking "Saiba mais" focuses the next card
    const carousel = document.querySelector("[data-po-carousel]");
    if (carousel) {
        const cards = Array.from(carousel.querySelectorAll(".po-highlight"));
        carousel.addEventListener("click", (event) => {
            const trigger = event.target.closest("[data-po-carousel-next]");
            if (!trigger) return;
            event.preventDefault();
            const current = trigger.closest(".po-highlight");
            const index = cards.indexOf(current);
            const next = cards[(index + 1) % cards.length];
            next.scrollIntoView({ behavior: "smooth", block: "nearest", inline: "center" });
        });
    }
});
