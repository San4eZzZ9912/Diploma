package com.diploma.robot_warehouse_backend.controller;

import com.diploma.robot_warehouse_backend.service.InboundImportService;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.*;

import java.nio.file.Path;

@RestController
@RequestMapping("/api/inbounds")
public class InboundImportController {

    private final InboundImportService inboundImportService;

    public InboundImportController(InboundImportService inboundImportService) {
        this.inboundImportService = inboundImportService;
    }

    /**
     * ВРЕМЕННЫЙ endpoint для локального тестирования
     *
     * Пример:
     * POST /api/inbounds/import?externalRef=0000007&path=C:\data\inbound_0000007.txt
     */
    @PostMapping("/import")
    public ResponseEntity<String> importFromPath(@RequestParam String externalRef, @RequestParam String path) {
        inboundImportService.importInbound(Path.of(path), externalRef);

        return ResponseEntity.ok("Imported inbound " + externalRef);
    }
}
