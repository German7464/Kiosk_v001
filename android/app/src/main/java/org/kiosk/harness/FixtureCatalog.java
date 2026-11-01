package org.kiosk.harness;

import java.util.List;

/** Build-owned expectations, never obtained from a candidate descriptor. */
public final class FixtureCatalog {
    public static final String JS = "9dbea16811df97b75c2b3e4db25fd468bf9de4a9d2f9fc1b6b3740f4b4ce53fc";
    public static final String CSS = "8662399cc92650fb31434a92240a7dda50f013d6be002de5c5d97d7d746ab37c";
    public static final List<String> NAMES = List.of("valid-kiosk", "valid-tv", "empty-kiosk", "empty-tv", "two-card-tv", "two-card-kiosk");
    private FixtureCatalog() {}
    public static String mode(String name) { require(name); return name.endsWith("-tv") ? "tv" : "kiosk"; }
    public static String identity(String name) {
        require(name);
        if (name.startsWith("two-card-")) return "0d027e264096337f7f37f3ca6dd128ed3e6622aa2491ee404f742bb7f5cd1d18";
        return name.startsWith("empty-")
            ? "bd6397715c21fb23d7d14a8052caa52fc8b6c53d83416db401e6b52ca6ccc7fd"
            : "3658670566f16d0cb77e0f58facc10bcb2ec518100764421d3510ef1a604edfa";
    }
    private static void require(String name) {
        if (!NAMES.contains(name)) throw new IllegalArgumentException("unknown_fixture");
    }
}
