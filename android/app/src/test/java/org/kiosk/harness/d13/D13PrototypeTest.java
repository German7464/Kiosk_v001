package org.kiosk.harness.d13;
import java.nio.file.*;
import org.junit.Test;
public class D13PrototypeTest {
    @Test public void syntheticInteropAndEnrollmentModel()throws Exception {
        Path root=Path.of(System.getProperty("preparationFixtureRoot")).getParent().resolve("d13-prototype");
        System.out.println("D13_REPORT="+StrictPrototypeJson.encode(D13Checks.run(Files.readAllBytes(root.resolve("vectors.json")),Files.readAllBytes(root.resolve("windows-signature-results.json")))));
    }
}
