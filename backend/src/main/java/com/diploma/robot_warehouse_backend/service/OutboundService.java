package com.diploma.robot_warehouse_backend.service;

import com.diploma.robot_warehouse_backend.dto.*;
import com.diploma.robot_warehouse_backend.entity.Outbound;
import com.diploma.robot_warehouse_backend.entity.OutboundLine;
import com.diploma.robot_warehouse_backend.entity.Product;
import com.diploma.robot_warehouse_backend.entity.Task;
import com.diploma.robot_warehouse_backend.enums.Status;
import com.diploma.robot_warehouse_backend.repository.OutboundLineRepository;
import com.diploma.robot_warehouse_backend.repository.OutboundRepository;
import com.diploma.robot_warehouse_backend.repository.ProductRepository;
import com.diploma.robot_warehouse_backend.repository.SlotStateRepository;
import com.diploma.robot_warehouse_backend.repository.TaskRepository;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

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
                           TaskRepository taskRepository,
                           SlotStateRepository slotStateRepository) {
        this.outboundRepository = outboundRepository;
        this.outboundLineRepository = outboundLineRepository;
        this.productRepository = productRepository;
        this.taskRepository = taskRepository;
        this.slotStateRepository = slotStateRepository;
    }

    @Transactional
    public OutboundCreateResult createOutbound(OutboundCreateRequest request) {
        if (request == null) {
            throw new IllegalArgumentException("Request is required");
        }

        if (request.getExternalRef() == null || request.getExternalRef().isBlank()) {
            throw new IllegalArgumentException("External ref is required");
        }

        if (outboundRepository.existsByExternalRef(request.getExternalRef())) {
            throw new IllegalArgumentException("External ref already exists");
        }

        if (request.getItems() == null || request.getItems().isEmpty()) {
            throw new IllegalArgumentException("At least one item is required");
        }

        // Сначала нормализуем позиции:
        // если пользователь добавил один и тот же товар несколько раз,
        // объединим количества в одну строку outbound.
        Map<Integer, Integer> mergedItems = new LinkedHashMap<>();

        for (OutboundItemRequest item : request.getItems()) {
            if (item == null) {
                throw new IllegalArgumentException("Item is null");
            }

            Integer productId = item.getProductId();
            Integer quantity = item.getQuantity();

            if (productId == null) {
                throw new IllegalArgumentException("Product id is required");
            }

            if (quantity == null || quantity <= 0) {
                throw new IllegalArgumentException("Quantity must be > 0");
            }

            mergedItems.merge(productId, quantity, Integer::sum);
        }

        // Полная валидация ДО создания outbound
        Map<Integer, Product> productsById = new LinkedHashMap<>();
        int totalTasks = 0;

        for (Map.Entry<Integer, Integer> entry : mergedItems.entrySet()) {
            Integer productId = entry.getKey();
            Integer quantity = entry.getValue();

            Product product = productRepository.findById(productId)
                    .orElseThrow(() -> new IllegalArgumentException("Product not found: " + productId));

            int available = slotStateRepository.countAvailableStorageByProductId(productId);
            if (quantity > available) {
                throw new IllegalStateException(
                        "Недостаточно товара на складе для productId=" + productId +
                                ". Запрошено=" + quantity + ", доступно=" + available
                );
            }

            productsById.put(productId, product);
            totalTasks += quantity;
        }

        // Создаём один outbound-заказ
        Outbound outbound = new Outbound(request.getExternalRef(), Status.NEW);
        outboundRepository.save(outbound);

        int linesCreated = 0;
        List<Task> allTasks = new ArrayList<>();

        // Для каждой строки корзины создаём OutboundLine и поштучные Task
        for (Map.Entry<Integer, Integer> entry : mergedItems.entrySet()) {
            Integer productId = entry.getKey();
            Integer quantity = entry.getValue();
            Product product = productsById.get(productId);

            OutboundLine outboundLine = new OutboundLine(outbound, product, quantity);
            outboundLineRepository.save(outboundLine);
            linesCreated++;

            for (int i = 0; i < quantity; i++) {
                Task task = new Task(Status.NEW, outboundLine, product);
                allTasks.add(task);
            }
        }

        taskRepository.saveAll(allTasks);

        return new OutboundCreateResult(outbound.getId(), linesCreated, totalTasks);
    }

    @Transactional(readOnly = true)
    public OutboundDetailsView getOutboundDetails(Integer outboundId) {
        Outbound outbound = outboundRepository.findById(outboundId)
                .orElseThrow(() -> new IllegalArgumentException("Outbound not found: " + outboundId));

        List<OutboundLine> lines = outboundLineRepository.findByOutboundIdWithProduct(outboundId);
        List<Task> tasks = taskRepository.findByOutboundIdWithProduct(outboundId);

        List<OutboundLineView> lineViews = lines.stream()
                .map(line -> new OutboundLineView(
                        line.getId(),
                        line.getProduct().getName(),
                        line.getProduct().getSku(),
                        line.getProduct().getManufacturer(),
                        line.getQuantity()
                ))
                .toList();

        List<OutboundTaskView> taskViews = tasks.stream()
                .map(task -> new OutboundTaskView(
                        task.getId(),
                        task.getProduct().getName(),
                        task.getProduct().getSku(),
                        task.getProduct().getManufacturer(),
                        task.getStatus()
                ))
                .toList();

        return new OutboundDetailsView(
                outbound.getId(),
                outbound.getExternalRef(),
                outbound.getStatus().name(),
                lineViews,
                taskViews
        );
    }
}