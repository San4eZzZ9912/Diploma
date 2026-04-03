package com.diploma.robot_warehouse_backend.controller;

import com.diploma.robot_warehouse_backend.dto.ParsedQr;
import com.diploma.robot_warehouse_backend.dto.PutawayTaskResponse;
import com.diploma.robot_warehouse_backend.dto.TaskCompleteRequest;
import com.diploma.robot_warehouse_backend.service.DeliveryDispatchService;
import com.diploma.robot_warehouse_backend.service.PutawayDispatchService;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.*;

@RestController
@RequestMapping("/api/robot/task/putaway")
public class RobotPutawayController {

    private final PutawayDispatchService putawayDispatchService;

    public RobotPutawayController(PutawayDispatchService putawayDispatchService) {
        this.putawayDispatchService = putawayDispatchService;
    }

    @GetMapping("/next")
    public ResponseEntity<PutawayTaskResponse> nextPutaway(@RequestParam String robotId) {
        return putawayDispatchService.getNextTask(robotId)
                .map(ResponseEntity::ok)
                .orElseGet(() -> ResponseEntity.noContent().build());
    }

    @PostMapping("/{taskId}/complete")
    public ResponseEntity<Void> completePutaway(@PathVariable Integer taskId,
                                         @RequestBody TaskCompleteRequest req) {

        ParsedQr qr = parseObservedQr(req.getObservedQr()); // sku/manufacturer or nulls

        putawayDispatchService.completeTask(taskId, req.getRobotId(), req.isSuccess(), qr.getSku(), qr.getManufacturer());

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

}

