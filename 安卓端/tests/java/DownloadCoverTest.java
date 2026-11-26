package io.github.maomaoyexi.videodownloader.prototype;

import com.yausername.youtubedl_android.YoutubeDLRequest;

import java.io.File;
import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.Arrays;
import java.util.Base64;

public final class DownloadCoverTest {
    private static final byte[] JPG = Base64.getDecoder().decode(
            "/9j/4AAQSkZJRgABAgAAAQABAAD//gAQTGF2YzYyLjI4LjEwMQD/2wBDAAgEBAQEBAUFBQUFBQYGBgYGBgYGBgYGBgYHBwcICAgHBwcGBgcHCAgICAkJCQgICAgJCQoKCgwMCwsODg4RERT/xABMAAEBAAAAAAAAAAAAAAAAAAAABwEBAQAAAAAAAAAAAAAAAAAABQcQAQAAAAAAAAAAAAAAAAAAAAARAQAAAAAAAAAAAAAAAAAAAAD/wAARCAACAAIDASIAAhEAAxEA/9oADAMBAAIRAxEAPwCOAL+Kf//Z");
    private static final byte[] PNG = Base64.getDecoder().decode(
            "iVBORw0KGgoAAAANSUhEUgAAAAIAAAACCAIAAAD91JpzAAAACXBIWXMAAAABAAAAAQBPJcTWAAAAEklEQVR4nGNkYPjHwMDAwgAGAAsiAQRmV5cZAAAAAElFTkSuQmCC");
    private static final byte[] WEBP = Base64.getDecoder().decode(
            "UklGRjgAAABXRUJQVlA4ICwAAACQAQCdASoCAAIAAgA0JaACdLoAA5gA/vmTb/+QH/+QH/+QH/8gP+IXeyAwAA==");

    public static void main(String[] args) throws IOException {
        Path work = Files.createTempDirectory("封面 100% ");
        try {
            YoutubeDLRequest request = new YoutubeDLRequest("https://youtu.be/jNQXAC9IVRw");
            DownloadCover.configure(request, work.toFile());
            if (!request.hasOption("--skip-download") || !request.hasOption("--write-thumbnail")
                    || !request.hasOption("--ignore-no-formats-error") || request.hasOption("--embed-thumbnail")) {
                throw new AssertionError(request.buildCommand());
            }
            String template = new File(work.toFile().getAbsolutePath().replace("%", "%%"), "cover.%(ext)s").getPath();
            if (!template.equals(request.getOption("-o"))) throw new AssertionError(request.buildCommand());

            expectImage(work, "cover.jpeg", JPG, "多.段名称 [demo] (1).mp4", "多.段名称 [demo] (1).jpg", "image/jpeg");
            expectImage(work, "cover.png", PNG, "只有音频.m4a", "只有音频.png", "image/png");
            expectImage(work, "cover.jpg", WEBP, "静音视频.mp4", "静音视频.webp", "image/webp");

            Files.write(work.resolve("stream-title.jpg"), JPG);
            Files.write(work.resolve("cover.webp.part"), WEBP);
            Files.write(work.resolve("cover.png"), Arrays.copyOf(PNG, PNG.length - 1));
            Files.write(work.resolve("cover.webp"), Arrays.copyOf(WEBP, WEBP.length - 1));
            Files.write(work.resolve("cover.jpeg"), Arrays.copyOf(JPG, JPG.length - 2));
            Files.write(work.resolve("cover.jpg"), "<html>temporary error</html>".getBytes(StandardCharsets.UTF_8));
            byte[] originalMedia = "saved media".getBytes(StandardCharsets.UTF_8);
            Path media = Files.write(work.resolve("title.mp4"), originalMedia);
            if (DownloadCover.find(work.toFile(), "title.mp4") != null) throw new AssertionError("Invalid cover accepted");
            if (!Arrays.equals(originalMedia, Files.readAllBytes(media))) throw new AssertionError("Media changed");
            System.out.println("封面命令、三种格式、媒体基名和不完整文件校验通过。");
        } finally {
            File[] files = work.toFile().listFiles();
            if (files != null) {
                for (File file : files) Files.deleteIfExists(file.toPath());
            }
            Files.deleteIfExists(work);
        }
    }

    private static void expectImage(Path directory, String fileName, byte[] bytes,
                                    String mediaName, String coverName, String mimeType) throws IOException {
        Path file = Files.write(directory.resolve(fileName), bytes);
        DownloadCover.Image image = DownloadCover.find(directory.toFile(), mediaName);
        if (image == null || !image.file.equals(file.toFile()) || !image.displayName.equals(coverName)
                || !image.mimeType.equals(mimeType)) throw new AssertionError(coverName);
        Files.delete(file);
    }
}
