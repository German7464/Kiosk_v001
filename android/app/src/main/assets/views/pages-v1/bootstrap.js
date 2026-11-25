"use strict";

(function () {
    const surface = document.getElementById("page-display");
    const source = document.getElementById("page-data");
    try {
        const data = JSON.parse(source.textContent);
        const media = Object.create(null);
        for (const event of Array.isArray(data.events) ? data.events : []) {
            for (const field of ["image_kiosk", "image_tv", "image_thumb"]) {
                const reference = event && event[field];
                if (typeof reference === "string" && reference.startsWith("/static/uploads/")) {
                    media[reference] = reference.slice(1);
                }
            }
        }
        const target = data.page && typeof data.page.target === "string" ? data.page.target : "";
        window.KioskPageDisplay.mount(surface, {
            page: data.page,
            events: data.events,
            tags: data.tags,
            mode: target.startsWith("tv-") ? "tv" : "kiosk",
            media: media
        });
    } catch (error) {
        if (surface) surface.textContent = "Content unavailable";
    }
})();
