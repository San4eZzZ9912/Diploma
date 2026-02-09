package com.diploma.robot_warehouse_backend.controller;

import com.diploma.robot_warehouse_backend.service.InboundImportService;
import org.springframework.stereotype.Controller;
import org.springframework.ui.Model;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.multipart.MultipartFile;

import java.nio.file.Files;
import java.nio.file.Path;

@Controller
@RequestMapping("/inbounds")
public class InboundUiController {
    private final InboundImportService inboundImportService;

    public InboundUiController(InboundImportService inboundImportService) {
        this.inboundImportService = inboundImportService;
    }

    @GetMapping("/upload")
    public String uploadForm() {
        return "inbounds/upload";
    }

    @PostMapping("/upload")
    public String handleUpload(@RequestParam String externalRef, @RequestParam("file") MultipartFile file, Model model) {
        if (file.isEmpty()) {
            model.addAttribute("error", "Файл не выбран");
            return "inbounds/upload";
        }

        if (externalRef == null || externalRef.isBlank()) {
            model.addAttribute("error", "Номер номенклатуры обязателен");
            return "inbounds/upload";
        }

        try {
            Path tmp = Files.createTempFile("inbound_","_" + file.getOriginalFilename());
            file.transferTo(tmp.toFile());

            inboundImportService.importInbound(tmp, externalRef);

            model.addAttribute("ok", "Импорт выполнен: " + externalRef);
            return "inbounds/upload";
        } catch (Exception e) {
            model.addAttribute("error", "Ошибка импорта: " + e.getMessage());
            return "inbounds/upload";
        }
    }
}
