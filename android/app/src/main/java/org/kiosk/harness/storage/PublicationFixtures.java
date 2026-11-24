package org.kiosk.harness.storage;
import java.util.*;
/** Independent build-owned PC1 pins. Closed development source, not production trust. */
public final class PublicationFixtures {
public record Pin(long size,String sha256) {}
public record Fixture(String key,String identity,Map<String,Pin> packageFiles,Map<String,Pin> viewFiles) { public long bytes(){return packageFiles.values().stream().mapToLong(Pin::size).sum()+viewFiles.values().stream().mapToLong(Pin::size).sum();} }
private PublicationFixtures() {}
private static Map<String,Pin> Apackage(){return Map.ofEntries(
Map.entry("data/events.json",new Pin(394L,"f07a1d8c45a0d421e43eb1a06e9a5658cebf302791827e3dd2be7a1cc0777b8e")),
Map.entry("manifest.json",new Pin(2088L,"3658670566f16d0cb77e0f58facc10bcb2ec518100764421d3510ef1a604edfa")),
Map.entry("resources/static/css/base.css",new Pin(55750L,"cf7d5b8b85c74ce247cf1bc70f79fef75cc5753977061e372a0eaaf96422165f")),
Map.entry("resources/static/img/site_icon.png",new Pin(445924L,"15a14a2e89ca81df61f42c806441d2a781b58abd559b5fe304dbaa948b9717e8")),
Map.entry("resources/static/js/admin_flash.js",new Pin(285L,"abea7f76eed3ad5f61f46a4cb4c981172f3195bfd0e79085762edc027e036750")),
Map.entry("resources/static/js/kiosk_events.js",new Pin(13066L,"1dec822b0d1749ce10caa6e97c5241c38540c62e7f74abbe62e5e7a5d1d62db1")),
Map.entry("resources/static/js/kiosk_home.js",new Pin(7801L,"f348e92d9453e5f1a00cbde3057831463b356de4d55d9ad6a5815f987416709e")),
Map.entry("resources/static/js/tv.js",new Pin(10129L,"b7e46df7bd5b87ccffa95281771593e893b6f15ed0455b6c38b326195d7a6e16")),
Map.entry("resources/templates/base.html",new Pin(968L,"875a10ed69a009a93c91837c861a68d3d89f60be1d4a6604313f226523bcb473")),
Map.entry("resources/templates/kiosk_events.html",new Pin(3519L,"fbffeb61907a12e4f51de98ac68e14c400e8cb2e5b76e0e8bdcff4d3d6682ea2")),
Map.entry("resources/templates/kiosk_home.html",new Pin(3251L,"4ac73391c9296885c49ade7e24de2787027b1c369d64f31f507fa148c840cd22")),
Map.entry("resources/templates/tv.html",new Pin(2235L,"655d25c78c520838b143477b6197e72db331fa703527a953cf2cdf0c45616196")),
Map.entry("resources/translations/de.json",new Pin(7666L,"1ff4644a411f39a03c9b463fd7ea55659ef1ce9cd3a86e038faf716b4cc14aba")),
Map.entry("resources/translations/en.json",new Pin(6763L,"d78678a856f64caf4ae183e983210c7535093e021f8a7d25f72b60682b037e20")),
Map.entry("resources/translations/ru.json",new Pin(9997L,"dfaae190b387d82ac9bd129c8a5b351c5605f6f1e38fb67bb84f2698a171241a")),
Map.entry("static/uploads/card.png",new Pin(76L,"4b02621a1639a302da7e368db30b5b96f931f6be98b1154b2e0d787986227a46")));}
private static Map<String,Pin> Aview(){return Map.ofEntries(
Map.entry("events.css",new Pin(2260L,"8662399cc92650fb31434a92240a7dda50f013d6be002de5c5d97d7d746ab37c")),
Map.entry("events.js",new Pin(6586L,"9dbea16811df97b75c2b3e4db25fd468bf9de4a9d2f9fc1b6b3740f4b4ce53fc")),
Map.entry("index.html",new Pin(7913L,"76a0510eecfa0d8c2a63e9f41c6435f0dc1c6293b8bd25f40267cdc4b5062fe6")),
Map.entry("static/uploads/card.png",new Pin(76L,"4b02621a1639a302da7e368db30b5b96f931f6be98b1154b2e0d787986227a46")),
Map.entry("view.json",new Pin(614L,"ad23bc75382653c4421f157bb135968e55c8ba649e8ece0cdefdbbbe5baeb27c")));}
public static final Fixture A=new Fixture("A","3658670566f16d0cb77e0f58facc10bcb2ec518100764421d3510ef1a604edfa",Apackage(),Aview());
private static Map<String,Pin> Bpackage(){return Map.ofEntries(
Map.entry("data/events.json",new Pin(681L,"17b3c86ed7f1d186b2fc85f2ce3c7d73fc91a502732216c328aa5999313f240a")),
Map.entry("manifest.json",new Pin(2088L,"0d027e264096337f7f37f3ca6dd128ed3e6622aa2491ee404f742bb7f5cd1d18")),
Map.entry("resources/static/css/base.css",new Pin(55750L,"cf7d5b8b85c74ce247cf1bc70f79fef75cc5753977061e372a0eaaf96422165f")),
Map.entry("resources/static/img/site_icon.png",new Pin(445924L,"15a14a2e89ca81df61f42c806441d2a781b58abd559b5fe304dbaa948b9717e8")),
Map.entry("resources/static/js/admin_flash.js",new Pin(285L,"abea7f76eed3ad5f61f46a4cb4c981172f3195bfd0e79085762edc027e036750")),
Map.entry("resources/static/js/kiosk_events.js",new Pin(13066L,"1dec822b0d1749ce10caa6e97c5241c38540c62e7f74abbe62e5e7a5d1d62db1")),
Map.entry("resources/static/js/kiosk_home.js",new Pin(7801L,"f348e92d9453e5f1a00cbde3057831463b356de4d55d9ad6a5815f987416709e")),
Map.entry("resources/static/js/tv.js",new Pin(10129L,"b7e46df7bd5b87ccffa95281771593e893b6f15ed0455b6c38b326195d7a6e16")),
Map.entry("resources/templates/base.html",new Pin(968L,"875a10ed69a009a93c91837c861a68d3d89f60be1d4a6604313f226523bcb473")),
Map.entry("resources/templates/kiosk_events.html",new Pin(3519L,"fbffeb61907a12e4f51de98ac68e14c400e8cb2e5b76e0e8bdcff4d3d6682ea2")),
Map.entry("resources/templates/kiosk_home.html",new Pin(3251L,"4ac73391c9296885c49ade7e24de2787027b1c369d64f31f507fa148c840cd22")),
Map.entry("resources/templates/tv.html",new Pin(2235L,"655d25c78c520838b143477b6197e72db331fa703527a953cf2cdf0c45616196")),
Map.entry("resources/translations/de.json",new Pin(7666L,"1ff4644a411f39a03c9b463fd7ea55659ef1ce9cd3a86e038faf716b4cc14aba")),
Map.entry("resources/translations/en.json",new Pin(6763L,"d78678a856f64caf4ae183e983210c7535093e021f8a7d25f72b60682b037e20")),
Map.entry("resources/translations/ru.json",new Pin(9997L,"dfaae190b387d82ac9bd129c8a5b351c5605f6f1e38fb67bb84f2698a171241a")),
Map.entry("static/uploads/card.png",new Pin(76L,"4b02621a1639a302da7e368db30b5b96f931f6be98b1154b2e0d787986227a46")));}
private static Map<String,Pin> Bview(){return Map.ofEntries(
Map.entry("events.css",new Pin(2260L,"8662399cc92650fb31434a92240a7dda50f013d6be002de5c5d97d7d746ab37c")),
Map.entry("events.js",new Pin(6586L,"9dbea16811df97b75c2b3e4db25fd468bf9de4a9d2f9fc1b6b3740f4b4ce53fc")),
Map.entry("index.html",new Pin(8195L,"07e5695168cabc96c31d833c8f5924ddacc9b1ba497d4ab7763cb29efb9ae44c")),
Map.entry("static/uploads/card.png",new Pin(76L,"4b02621a1639a302da7e368db30b5b96f931f6be98b1154b2e0d787986227a46")),
Map.entry("view.json",new Pin(614L,"03d7810273353c846268f2f8db8e26f36d671966478a4d610a8de95c6f5d23ae")));}
public static final Fixture B=new Fixture("B","0d027e264096337f7f37f3ca6dd128ed3e6622aa2491ee404f742bb7f5cd1d18",Bpackage(),Bview());
public static final String BUILD="b4cb5f181559e8f40fccb99ea0edb631fcb18c3c9e60d47a49347deee3bfa354";
public static final long STAGING_BYTES=Math.max(A.bytes(),B.bytes());
public static Fixture key(String key){if("A".equals(key))return A;if("B".equals(key))return B;throw new IllegalArgumentException("unknown_fixture");}
public static Fixture identity(String id){if(A.identity().equals(id))return A;if(B.identity().equals(id))return B;throw new IllegalArgumentException("unknown_revision");}

private static Map<String,Pin> Akiosk(){return Map.ofEntries(Map.entry("events.css",new Pin(2260L,"8662399cc92650fb31434a92240a7dda50f013d6be002de5c5d97d7d746ab37c")),
Map.entry("events.js",new Pin(6586L,"9dbea16811df97b75c2b3e4db25fd468bf9de4a9d2f9fc1b6b3740f4b4ce53fc")),
Map.entry("index.html",new Pin(7916L,"9cd79eecf33c4414604f6f0b3c6344813e328b6bd10e2a9c5a6e8fdb27c139bc")),
Map.entry("static/uploads/card.png",new Pin(76L,"4b02621a1639a302da7e368db30b5b96f931f6be98b1154b2e0d787986227a46")),
Map.entry("view.json",new Pin(617L,"c47738f16db90906edd2c97dacd746566bfaabf4c08b5d8a530f64006baa4012")));}
private static Map<String,Pin> Bkiosk(){return Map.ofEntries(Map.entry("events.css",new Pin(2260L,"8662399cc92650fb31434a92240a7dda50f013d6be002de5c5d97d7d746ab37c")),
Map.entry("events.js",new Pin(6586L,"9dbea16811df97b75c2b3e4db25fd468bf9de4a9d2f9fc1b6b3740f4b4ce53fc")),
Map.entry("index.html",new Pin(8198L,"a3c0160dd6cbab42604d1fb4ae8eefee203398eb811091305ee2ee2b83cf657f")),
Map.entry("static/uploads/card.png",new Pin(76L,"4b02621a1639a302da7e368db30b5b96f931f6be98b1154b2e0d787986227a46")),
Map.entry("view.json",new Pin(617L,"dd8ac94a73bd08cf4b0e2517eda3cb65f744bdbf1c598044cad63d26b13cdd29")));}
public static String mode(String mode){if(!Set.of("tv","kiosk").contains(mode))throw new IllegalArgumentException("unknown_mode");return mode;}
public static Map<String,Pin> viewFiles(Fixture f,String mode){return mode(mode).equals("tv")?f.viewFiles():(f.key().equals("A")?Akiosk():Bkiosk());}
public static final String KIOSK_BUILD="4db2503727b8b989bab5ec933a3ee4bcb21ab179cc49ceffec23c7aeda82ad7a";
public static String build(String mode){return mode(mode).equals("tv")?BUILD:KIOSK_BUILD;}
}
