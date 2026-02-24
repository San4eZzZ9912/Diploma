package com.diploma.robot_warehouse_backend.controller;

import com.diploma.robot_warehouse_backend.dto.DeliveryTaskResponse;
import com.diploma.robot_warehouse_backend.dto.TaskCompleteRequest;
import com.diploma.robot_warehouse_backend.service.DeliveryDispatchService;
import org.springframework.http.ResponseEntity;
import org.springframework.stereotype.Controller;
import org.springframework.web.bind.annotation.*;

@RestController
@RequestMapping("/api/robot/delivery")
public class RobotDeliveryController {
    private final DeliveryDispatchService deliveryDispatchService;

    public RobotDeliveryController(DeliveryDispatchService deliveryDispatchService) {
        this.deliveryDispatchService = deliveryDispatchService;
    }

    @GetMapping("/next")
    public ResponseEntity<DeliveryTaskResponse> next(@RequestParam String robotId) {
        return deliveryDispatchService.getNextDeliveryTask(robotId)
                .map(ResponseEntity::ok)
                .orElseGet(() -> ResponseEntity.noContent().build());
    }

    @PostMapping("/{taskId}/complete")
    public ResponseEntity<Void> complete(@PathVariable Integer taskId, @RequestBody TaskCompleteRequest request) {
        deliveryDispatchService.completeDeliveryTask(taskId, request.getRobotId(), request.isSuccess());
        return ResponseEntity.ok().build();
    }
}
