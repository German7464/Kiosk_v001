const tagSearch = document.querySelector("[data-tag-search]");
const tagItems = document.querySelectorAll("[data-tag-item]");

if (tagSearch) {
    tagSearch.addEventListener("input", () => {
        const query = tagSearch.value.trim().toLowerCase();

        tagItems.forEach((item) => {
            item.hidden = query && !item.dataset.tagName.includes(query);
        });
    });
}
