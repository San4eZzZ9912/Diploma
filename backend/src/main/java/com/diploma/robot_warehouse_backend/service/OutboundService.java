package com.diploma.robot_warehouse_backend.service;

import com.diploma.robot_warehouse_backend.dto.OutboundCreateResult;
import com.diploma.robot_warehouse_backend.entity.Outbound;
import com.diploma.robot_warehouse_backend.entity.OutboundLine;
import com.diploma.robot_warehouse_backend.entity.Product;
import com.diploma.robot_warehouse_backend.entity.Task;
import com.diploma.robot_warehouse_backend.enums.Status;
import com.diploma.robot_warehouse_backend.repository.*;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import java.util.ArrayList;
import java.util.List;

@Service
public class OutboundService {
    private final OutboundRepository outboundRepository;
    private final OutboundLineRepository outboundLineRepository;
    private final ProductRepository productRepository;
    private final TaskRepository taskRepository;
    private final SlotStateRepository slotStateRepository;

    public OutboundService(OutboundRepository outboundRepository,
                           OutboundLineRepository outboundLineRepository,
                           ProductRepository productRepository,
                           TaskRepository taskRepository, SlotStateRepository slotStateRepository) {
        this.outboundRepository = outboundRepository;
        this.outboundLineRepository = outboundLineRepository;
        this.productRepository = productRepository;
        this.taskRepository = taskRepository;
        this.slotStateRepository = slotStateRepository;
    }

    @Transactional
    public OutboundCreateResult createOutbound(String externalRef, Integer productId, int quantity) {
        if (externalRef.isBlank() || externalRef == null) {
            throw new IllegalArgumentException("External ref is required");
        }

        if (quantity <= 0) {
            throw new IllegalArgumentException("Quantity must be > 0");
        }

        if (outboundRepository.existsByExternalRef(externalRef)) {
            throw new IllegalArgumentException("External ref already exists");
        }

        int available = slotStateRepository.countAvailableStorageByProductId(productId);
        if (quantity > available) {
            throw new IllegalStateException(
                    "Недостаточно товара на складе. Запрошено=" + quantity + ", доступно=" + available
            );
        }

        Product product = productRepository.findById(productId)
                .orElseThrow(() -> new IllegalArgumentException("Product not found"));


        Outbound outbound = new Outbound(externalRef, Status.NEW);
        outboundRepository.save(outbound);

        OutboundLine outboundLine = new OutboundLine(outbound, product, quantity);
        outboundLineRepository.save(outboundLine);

        List<Task> tasks = new ArrayList<>();
        for (int i = 0; i < quantity; i++) {
            Task task = new Task(Status.NEW, outboundLine, product);
            tasks.add(task);
        }
        taskRepository.saveAll(tasks);

        return new OutboundCreateResult(outbound.getId(), 1, quantity);
    }
}
