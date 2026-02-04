package com.diploma.robot_warehouse_backend.service;

import com.diploma.robot_warehouse_backend.dto.InboundImportResult;
import com.diploma.robot_warehouse_backend.entity.*;
import com.diploma.robot_warehouse_backend.enums.Status;
import com.diploma.robot_warehouse_backend.repository.*;
import jakarta.persistence.criteria.CriteriaBuilder;
import jakarta.transaction.Transactional;
import org.springframework.stereotype.Service;

import java.io.BufferedReader;
import java.io.File;
import java.io.FileReader;
import java.io.IOException;
import java.nio.file.Files;
import java.nio.file.Path;
import java.time.LocalDateTime;
import java.util.ArrayList;
import java.util.List;


@Service
public class InboundImportService {
    private final InboundRepository inboundRepository;
    private final ProductRepository productRepository;
    private final TaskRepository taskRepository;
    private final InboundLineRepository inboundLineRepository;

    public InboundImportService(InboundRepository inboundRepository, ProductRepository productRepository, TaskRepository taskRepository, SlotStateRepository slotStateRepository, InboundLineRepository inboundLineRepository) {
        this.inboundRepository = inboundRepository;
        this.productRepository = productRepository;
        this.taskRepository = taskRepository;
        this.inboundLineRepository = inboundLineRepository;
    }

    @Transactional
    public InboundImportResult importInbound(Path filePath, String externalRef) {
        validateFile(filePath);

        if (inboundRepository.existsByExternalRef(externalRef)) {
            throw new IllegalArgumentException("Already imported: " + externalRef);
        }

        String fileName = filePath.getFileName().toString();

        Inbound inbound = new Inbound("FILE", externalRef, fileName, Status.NEW);
        inboundRepository.save(inbound);

        int tasksCreated = 0;
        int linesCreated = 0;

        try (BufferedReader reader = new BufferedReader(new FileReader(filePath.toFile()))) {
            String line;
            int lineNum = 0;
            while((line = reader.readLine()) != null) {
                lineNum++;

                if (lineNum == 1) {
                    continue;
                }


                line.trim();

                if (line.isEmpty()) {
                    continue;
                }
                String[] parts = line.split(";");
                String sku = parts[0].trim();
                String manufacturer = parts[1].trim();
                String name = parts[2].trim();
                Integer quantity = Integer.parseInt(parts[3]);

                Product product = productRepository.findBySkuAndManufacturer(sku, manufacturer)
                        .orElseGet(() -> {
                            Product p = new Product(sku, manufacturer, name);
                            return productRepository.save(p);
                        });

                InboundLine inboundLine = new InboundLine(inbound, product, quantity);
                inboundLineRepository.save(inboundLine);

                List<Task> tasks = new ArrayList<>();

                for (int i = 0; i < quantity; i++) {
                    Task task = new Task(Status.NEW, inboundLine, product);
                    tasks.add(task);
                    tasksCreated++;
                }
                taskRepository.saveAll(tasks);
            }

        } catch (IOException e) {
            throw new RuntimeException(e);
        }

        return new InboundImportResult(inbound.getId(), linesCreated, tasksCreated, fileName);
    }

    private void validateFile(Path filePath) {
        try {
            if (!Files.exists(filePath)) {
                throw new IllegalArgumentException("File does not exist: " + filePath);
            }
            if (!Files.isRegularFile(filePath)) {
                throw new IllegalArgumentException("Not a regular file: " + filePath);
            }
            if (!Files.isReadable(filePath)) {
                throw new IllegalArgumentException("File is not readable: " + filePath);
            }
            if (Files.size(filePath) == 0) {
                throw new IllegalArgumentException("File is empty: " + filePath);
            }
        } catch (java.io.IOException e) {
            throw new IllegalStateException("Cannot access file: " + filePath, e);
        }
    }

}
