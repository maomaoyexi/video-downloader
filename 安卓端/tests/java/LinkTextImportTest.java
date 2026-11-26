package io.github.maomaoyexi.videodownloader.prototype;

import java.io.ByteArrayInputStream;
import java.io.IOException;
import java.nio.charset.StandardCharsets;

final class LinkTextImportTest {
    private static final String LINKS = "https://youtu.be/jNQXAC9IVRw\nhttps://www.bilibili.com/video/BV1bK411W797?p=2";

    public static void main(String[] args) throws IOException {
        String input = "  # 视频链接\r\n\r\n\t" + LINKS.replace("\n", " \r\n\t") + "\r";
        expect(("\ufeff" + input).getBytes(StandardCharsets.UTF_8), input);
        expect(input.getBytes(StandardCharsets.UTF_16), input);
        expectRejected(new byte[]{(byte) 0xc3, 0x28}, "UTF-8");
        expectRejected("\0https://youtu.be/jNQXAC9IVRw".getBytes(StandardCharsets.UTF_8), "无效");
        expectRejected("# 只有注释\n".getBytes(StandardCharsets.UTF_8), "没有链接");
        expectRejected(new byte[128 * 1024 + 1], "128 KiB");
        System.out.println("TXT 导入编码、注释、换行和大小限制通过。");
    }

    private static void expect(byte[] input, String expected) throws IOException {
        String imported = LinkTextImport.read(new ByteArrayInputStream(input));
        if (!expected.equals(imported)) throw new AssertionError(imported);
    }

    private static void expectRejected(byte[] input, String message) throws IOException {
        try {
            LinkTextImport.read(new ByteArrayInputStream(input));
        } catch (LinkTextImport.InvalidText error) {
            if (!error.getMessage().contains(message)) throw new AssertionError(error);
            return;
        }
        throw new AssertionError("应当拒绝该内容");
    }
}
