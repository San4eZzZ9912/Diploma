package com.diploma.robot_warehouse_backend.controller;

import com.diploma.robot_warehouse_backend.dto.TaskCompleteRequest;
import com.diploma.robot_warehouse_backend.dto.TaskResponse;
import com.diploma.robot_warehouse_backend.service.TaskDispatchService;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.*;

@RestController
@RequestMapping("/api/robot/tasks")
public class RobotTaskController {

    private final TaskDispatchService taskDispatchService;

    public RobotTaskController(TaskDispatchService taskDispatchService) {
        this.taskDispatchService = taskDispatchService;
    }

    @GetMapping("/next")
    public ResponseEntity<TaskResponse> next(@RequestParam String robotId) {
        return taskDispatchService.getNextTask(robotId)
                .map(ResponseEntity::ok)
                .orElseGet(() -> ResponseEntity.noContent().build());
    }

    @PostMapping("/{taskId}/complete")
    public ResponseEntity<Void> complete(@PathVariable Integer taskId,
                                         @RequestBody TaskCompleteRequest req) {

        ParsedQr qr = parseObservedQr(req.getObservedQr()); // sku/manufacturer or nulls

        taskDispatchService.completeTask(taskId, req.getRobotId(), req.isSuccess(), qr.sku(), qr.manufacturer());

        return ResponseEntity.ok().build();
    }

    // --- helpers ---

    private ParsedQr parseObservedQr(String observedQr) {
        if (observedQr == null) return new ParsedQr(null, null);

        String s = observedQr.trim();
        if (s.isEmpty()) return new ParsedQr(null, null);

        String[] parts = s.split("/", 2);
        if (parts.length != 2) {
            // можно мягко: вернуть (null,null), либо жёстко: кинуть IllegalArgumentException
            throw new IllegalArgumentException("observedQr must be 'sku/manufacturer', got: " + observedQr);
        }

        String sku = parts[0].trim();
        String manufacturer = parts[1].trim();

        if (sku.isEmpty() || manufacturer.isEmpty()) {
            throw new IllegalArgumentException("observedQr must contain non-empty sku and manufacturer: " + observedQr);
        }

        return new ParsedQr(sku, manufacturer);
    }

    private record ParsedQr(String sku, String manufacturer) {}
}

